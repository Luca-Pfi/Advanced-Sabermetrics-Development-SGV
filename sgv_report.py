"""
HTML leaderboards for SGV records (self-contained, no extra libraries).

Per season, for qualified starters:
  * SGV Leaders           - ranked by SGV W minus SGV L (top 10, expandable, sortable)
  * Hard Luck             - SGV record most BETTER than the real W-L record
  * Fortunate             - SGV record most WORSE than the real W-L record

"Swing" = (SGV W - SGV L) - (Actual W - Actual L), in net wins.

Below the boards, a player search covers every starter of the selected season
and shows the SGV season line, a per-start SGV chart and the game log.
"""

import json

TOP_N = 10


def min_starts(team_games):
    """Qualifier: 1 start per 8 team games (20 GS over a full 162-game season)."""
    return max(1, round(team_games / 8))


def season_boards(df, season, team_games):
    s = df[df["season"] == season]
    qualifier = min_starts(team_games)
    rows = []
    for _, p in s.groupby("pitcher_id"):
        if len(p) < qualifier:
            continue
        sw, sl, snd = ((p["SGV_dec"] == d).sum() for d in ("W", "L", "ND"))
        aw, al, and_ = ((p["actual_dec"] == d).sum() for d in ("W", "L", "ND"))
        rows.append({
            "name": p["pitcher"].iloc[-1],
            "team": "/".join(dict.fromkeys(p["team"])),
            "gs": len(p),
            "sgv": [int(sw), int(sl), int(snd)],
            "act": [int(aw), int(al), int(and_)],
            "avg": round(float(p["SGV"].mean()), 2),
            "swing": int((sw - sl) - (aw - al)),
        })
    ranked = sorted(rows, key=lambda r: (-(r["sgv"][0] - r["sgv"][1]), r["avg"]))
    for i, r in enumerate(ranked, 1):
        r["rank"] = i
    hard_luck = sorted([r for r in rows if r["swing"] > 0],
                       key=lambda r: (-r["swing"], r["avg"]))[:TOP_N]
    fortunate = sorted([r for r in rows if r["swing"] < 0],
                       key=lambda r: (r["swing"], -r["avg"]))[:TOP_N]
    return {"season": season, "qualifier": qualifier, "qualified": len(rows),
            "all": ranked, "hardLuck": hard_luck, "fortunate": fortunate}


def season_pitchers(df, season, qualifier):
    """Every starter of a season, compact, for the player search."""
    s = df[df["season"] == season].sort_values("date")
    players = []
    for pid, p in s.groupby("pitcher_id"):
        sw, sl, snd = (int((p["SGV_dec"] == d).sum()) for d in ("W", "L", "ND"))
        aw, al, and_ = (int((p["actual_dec"] == d).sum()) for d in ("W", "L", "ND"))
        outs = [int(round(ip * 3)) for ip in p["IP"]]
        players.append({
            "id": int(pid), "n": p["pitcher"].iloc[-1], "t": "/".join(dict.fromkeys(p["team"])),
            "s": [sw, sl, snd], "a": [aw, al, and_],
            "outs": sum(outs), "er": int(p["ER"].sum()), "avg": round(float(p["SGV"].mean()), 2),
            "q": len(p) >= qualifier,
            # one start: date, opponent, H/A, outs, ER, SGV, SGV decision, real decision, team result
            "g": [[r.date[5:], r.opponent, r.home_away, o, int(r.ER), round(float(r.SGV), 2),
                   r.SGV_dec, r.actual_dec, r.team_result]
                  for r, o in zip(p.itertuples(), outs)],
        })
    # SGV rank among qualified starters, same order as the SGV Leaders board
    ranked = sorted((x for x in players if x["q"]), key=lambda x: (-(x["s"][0] - x["s"][1]), x["avg"]))
    for i, x in enumerate(ranked, 1):
        x["rank"] = i
    return sorted(players, key=lambda x: x["n"])


def write_report(df, league_rows, thresholds, path):
    league = {r["season"]: r for r in league_rows}
    seasons = sorted(df["season"].unique())
    data = []
    for s in seasons:
        board = season_boards(df, int(s), league[s]["team_games"])
        t = thresholds[s]
        starts = df[df["season"] == s]
        board.update({
            "wCut": round(t["sgv_w_below"], 2), "lCut": round(t["sgv_l_above"], 2),
            "band": f"{t['nd_band']:.0%}–{1 - t['nd_band']:.0%}",
            "calibratedOn": t["calibrated_on"],
            "currentWeight": league[s]["current_weight"],
            "ra9": round(league[s]["bullpen_ra9"], 2),
            "rpg": round(league[s]["runs_per_team_game"], 2),
            "totals": {"starts": len(starts),
                       **{d: int((starts["SGV_dec"] == d).sum()) for d in ("W", "L", "ND")}},
            "players": season_pitchers(df, int(s), board["qualifier"]),
        })
        data.append(board)
    meta = {"through": str(df["date"].max())}   # last game in the data, not the run time
    page = TEMPLATE.replace("__DATA__", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    page = page.replace("__META__", json.dumps(meta))
    path.write_text(page, encoding="utf-8")


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SGV Leaderboards</title>
<meta name="description" content="Starter Game Value: a win, loss or no-decision for every MLB start, earned by the pitching alone.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Roboto+Condensed:wght@500;700;800&family=Roboto:wght@400;500;700&display=swap" rel="stylesheet">
<style>
:root {
  color-scheme: light;
  --navy: #041e42; --navy-2: #0c2c56; --red: #bf0d3e;
  --bg: #f2f3f5; --surface: #ffffff; --line: #d9dde3; --line-soft: #eceef1; --zebra: #f7f8fa;
  --ink: #0b1320; --ink-2: #47505e; --ink-3: #6f7886;
  --win: #1d63c9; --nd: #a3abb8; --loss: #c8102e;
  --win-tint: #e3edfa; --loss-tint: #fbe5e9;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --navy: #031631; --navy-2: #0a2346; --red: #e0294f;
    --bg: #07111f; --surface: #0e1a2e; --line: #23324a; --line-soft: #18263d; --zebra: #111f35;
    --ink: #f1f4f8; --ink-2: #b6c0ce; --ink-3: #8592a6;
    --win: #4a8fe8; --nd: #46526a; --loss: #e5546e;
    --win-tint: #15305a; --loss-tint: #47192a;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --navy: #031631; --navy-2: #0a2346; --red: #e0294f;
  --bg: #07111f; --surface: #0e1a2e; --line: #23324a; --line-soft: #18263d; --zebra: #111f35;
  --ink: #f1f4f8; --ink-2: #b6c0ce; --ink-3: #8592a6;
  --win: #4a8fe8; --nd: #46526a; --loss: #e5546e;
  --win-tint: #15305a; --loss-tint: #47192a;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; scroll-padding-top: 64px; }
body { margin: 0; background: var(--bg); color: var(--ink);
       font: 14px/1.45 Roboto, "Helvetica Neue", Arial, sans-serif; }
a { color: inherit; }
.wrap { max-width: 1140px; margin: 0 auto; padding: 0 16px; }
.cond { font-family: "Roboto Condensed", "Arial Narrow", Roboto, sans-serif; }
.num { font-variant-numeric: tabular-nums; }

/* ---- top bar + season nav ---- */
.topbar { background: var(--navy); color: #fff; border-bottom: 3px solid var(--red); }
.topbar-in { display: flex; align-items: center; justify-content: space-between; gap: 16px; height: 56px; }
.brand { display: flex; align-items: center; gap: 12px; text-decoration: none; }
.brand-mark { font: 800 22px/1 "Roboto Condensed", "Arial Narrow", sans-serif; letter-spacing: .02em;
              background: #fff; color: var(--navy); padding: 6px 8px 5px; border-radius: 3px; }
.brand-name { font: 700 17px/1 "Roboto Condensed", "Arial Narrow", sans-serif; text-transform: uppercase;
              letter-spacing: .04em; }
.topbar-meta { display: flex; align-items: center; gap: 18px; font-size: 12.5px; color: #c9d3e3; }
.topbar-meta a { color: #fff; text-decoration: none; font-weight: 500; }
.topbar-meta a:hover { text-decoration: underline; }
.subnav { background: var(--surface); border-bottom: 1px solid var(--line); position: sticky; top: 0; z-index: 20; }
.subnav-in { display: flex; align-items: stretch; justify-content: space-between; gap: 16px; }
.tabs { display: flex; }
.tabs button { border: 0; background: none; cursor: pointer; padding: 14px 16px 11px; color: var(--ink-2);
               font: 700 15px/1 "Roboto Condensed", "Arial Narrow", sans-serif; letter-spacing: .03em;
               border-bottom: 3px solid transparent; }
.tabs button[aria-selected="true"] { color: var(--ink); border-bottom-color: var(--red); }
.tabs button:hover { color: var(--ink); }
.jump { display: flex; align-items: center; gap: 18px; font-size: 13px; }
.jump a { text-decoration: none; color: var(--ink-2); font-weight: 500; }
.jump a:hover { color: var(--ink); text-decoration: underline; }

/* ---- intro + scoreboard ---- */
.intro { display: grid; grid-template-columns: minmax(0, 1fr) 430px; gap: 28px; padding-top: 28px; padding-bottom: 8px; }
h1 { font: 800 34px/1.05 "Roboto Condensed", "Arial Narrow", sans-serif; text-transform: uppercase;
     letter-spacing: .01em; margin: 0 0 10px; }
.lede { margin: 0 0 14px; color: var(--ink-2); font-size: 15px; max-width: 62ch; }
.formula { margin: 0; padding: 10px 12px; border-left: 3px solid var(--red); background: var(--surface);
           font: 13px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; overflow-wrap: break-word; }
.scoreboard { background: var(--navy); color: #fff; border-radius: 4px; overflow: hidden; align-self: start; }
.sb-head { display: flex; justify-content: space-between; align-items: baseline; padding: 10px 14px;
           background: var(--navy-2); font: 700 14px/1 "Roboto Condensed", "Arial Narrow", sans-serif;
           text-transform: uppercase; letter-spacing: .05em; }
.sb-head span { color: #c9d3e3; font-weight: 500; font-size: 12px; letter-spacing: .02em; text-transform: none;
                font-family: Roboto, sans-serif; }
.sb-grid { display: grid; grid-template-columns: repeat(4, 1fr); }
.sb-cell { padding: 10px 14px 12px; border-top: 1px solid rgba(255,255,255,.12); }
.sb-cell + .sb-cell { border-left: 1px solid rgba(255,255,255,.12); }
.sb-grid .sb-cell:nth-child(4n+1) { border-left: 0; }
.sb-k { font: 500 11px/1.2 "Roboto Condensed", "Arial Narrow", sans-serif; text-transform: uppercase;
        letter-spacing: .06em; color: #aebbd0; }
.sb-v { font: 700 24px/1.1 "Roboto Condensed", "Arial Narrow", sans-serif; font-variant-numeric: tabular-nums; }
.sb-v.w { color: #8fbaf5; } .sb-v.l { color: #ff8fa3; }

/* ---- sections + tables ---- */
.block { margin-top: 28px; }
.block-head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; flex-wrap: wrap;
              border-bottom: 2px solid var(--ink); padding-bottom: 6px; margin-bottom: 0; }
h2 { font: 800 21px/1.1 "Roboto Condensed", "Arial Narrow", sans-serif; text-transform: uppercase;
     letter-spacing: .02em; margin: 0; }
.block-note { margin: 0; color: var(--ink-3); font-size: 12.5px; }
.block-desc { margin: 8px 0 10px; color: var(--ink-2); font-size: 13px; }
.key { display: flex; gap: 14px; flex-wrap: wrap; font-size: 12px; color: var(--ink-2); margin: 0 0 8px; }
.key span { display: inline-flex; align-items: center; gap: 5px; }
.sw { width: 10px; height: 10px; display: inline-block; border-radius: 2px; }
.ring { width: 10px; height: 10px; border-radius: 50%; border: 2px solid var(--ink-3); display: inline-block; }
.fill { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
.table-wrap { overflow-x: auto; background: var(--surface); border: 1px solid var(--line); border-top: 0; }
table.stats { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; font-size: 13.5px; }
.stats th { font: 700 11.5px/1 "Roboto Condensed", "Arial Narrow", sans-serif; text-transform: uppercase;
            letter-spacing: .05em; color: var(--ink-2); text-align: right; padding: 10px 10px 9px;
            background: var(--surface); border-bottom: 1px solid var(--line); white-space: nowrap; }
.stats th.sortable { cursor: pointer; user-select: none; }
.stats th.sortable:hover { color: var(--ink); }
.stats th[aria-sort="ascending"]::after { content: " ▲"; font-size: 9px; color: var(--red); }
.stats th[aria-sort="descending"]::after { content: " ▼"; font-size: 9px; color: var(--red); }
.stats td { padding: 8px 10px; text-align: right; border-bottom: 1px solid var(--line-soft); white-space: nowrap; }
.stats tbody tr:nth-child(even) td { background: var(--zebra); }
.stats tbody tr:hover td { background: var(--line-soft); }
.stats .l { text-align: left; }
.stats .rk { width: 36px; color: var(--ink-3); font-weight: 500; }
.player { font-weight: 700; }
.player a { text-decoration: none; }
.player a:hover { text-decoration: underline; color: var(--win); }
.tm { color: var(--ink-3); font-weight: 400; font-size: 12px; margin-left: 6px; }
.rec { font-weight: 700; }
.pill { display: inline-block; min-width: 38px; padding: 2px 6px; border-radius: 3px; font-weight: 700;
        text-align: center; }
.pill.pos { background: var(--win-tint); color: var(--win); }
.pill.neg { background: var(--loss-tint); color: var(--loss); }
.dist { display: flex; height: 12px; gap: 2px; min-width: 140px; }
.dist i { display: block; height: 100%; border-radius: 2px; }
.col-viz { width: 34%; }
.col-viz svg { display: block; width: 100%; height: 22px; }
.more { margin: 10px 0 0; border: 1px solid var(--ink); background: var(--surface); color: var(--ink);
        font: 700 13px/1 "Roboto Condensed", "Arial Narrow", sans-serif; text-transform: uppercase;
        letter-spacing: .05em; padding: 9px 14px; cursor: pointer; border-radius: 3px; }
.more:hover { background: var(--ink); color: var(--surface); }
.split { display: grid; grid-template-columns: 1fr 1fr; gap: 28px; }
.split .block { min-width: 0; }

/* ---- player search ---- */
.search { position: relative; max-width: 460px; margin: 12px 0 4px; }
.search input { width: 100%; padding: 11px 12px 11px 38px; font: 15px Roboto, sans-serif; color: var(--ink);
                background: var(--surface); border: 1px solid var(--line); border-radius: 3px; }
.search input:focus { outline: 2px solid var(--win); outline-offset: 0; border-color: var(--win); }
.search svg { position: absolute; left: 12px; top: 50%; transform: translateY(-50%); width: 16px; height: 16px;
              stroke: var(--ink-3); fill: none; stroke-width: 2; pointer-events: none; }
.search ul { position: absolute; z-index: 30; left: 0; right: 0; top: calc(100% + 2px); margin: 0; padding: 0;
             list-style: none; background: var(--surface); border: 1px solid var(--line);
             box-shadow: 0 8px 24px rgba(4,30,66,.14); max-height: 300px; overflow-y: auto; }
.search li { padding: 9px 12px; cursor: pointer; display: flex; justify-content: space-between; gap: 12px;
             border-bottom: 1px solid var(--line-soft); font-weight: 500; }
.search li span { color: var(--ink-3); font-size: 12.5px; font-weight: 400; }
.search li[aria-selected="true"], .search li:hover { background: var(--line-soft); }
.pcard { margin-top: 14px; background: var(--surface); border: 1px solid var(--line); }
.pcard-head { background: var(--navy); color: #fff; padding: 14px 16px; border-bottom: 3px solid var(--red);
              display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap; }
.pcard-head h3 { margin: 0; font: 800 28px/1 "Roboto Condensed", "Arial Narrow", sans-serif;
                 text-transform: uppercase; letter-spacing: .01em; }
.pcard-head span { color: #c9d3e3; font-size: 13px; }
.statline { display: grid; grid-template-columns: repeat(auto-fit, minmax(96px, 1fr)); border-bottom: 1px solid var(--line); }
.statline > div { padding: 10px 14px; border-right: 1px solid var(--line-soft); }
.statline .k { font: 700 11px/1.2 "Roboto Condensed", "Arial Narrow", sans-serif; text-transform: uppercase;
               letter-spacing: .06em; color: var(--ink-3); }
.statline .v { font: 700 24px/1.15 "Roboto Condensed", "Arial Narrow", sans-serif; font-variant-numeric: tabular-nums; }
.statline .s { font-size: 12px; color: var(--ink-2); }
.pcard-body { padding: 12px 16px 14px; }
.pcard-body h4 { margin: 4px 0 6px; font: 700 13px/1 "Roboto Condensed", "Arial Narrow", sans-serif;
                 text-transform: uppercase; letter-spacing: .06em; color: var(--ink-2); }
.pcard-body svg { display: block; width: 100%; height: auto; }
.axis { fill: var(--ink-3); font-size: 11px; font-family: Roboto, sans-serif; }
.note { color: var(--ink-3); font-size: 12px; margin: 6px 0 0; }
.dec { display: inline-block; min-width: 30px; padding: 1px 5px; border-radius: 2px; text-align: center;
       font: 700 11.5px/1.4 "Roboto Condensed", "Arial Narrow", sans-serif; color: #fff; }
.dec-W { background: var(--win); } .dec-L { background: var(--loss); }
.dec-ND { background: var(--nd); color: var(--ink); }
details.log { margin-top: 12px; border-top: 1px solid var(--line); }
details.log summary { cursor: pointer; padding: 10px 0; font: 700 13px/1 "Roboto Condensed", "Arial Narrow", sans-serif;
                      text-transform: uppercase; letter-spacing: .06em; color: var(--ink-2); }
details.log .table-wrap { border: 1px solid var(--line); }
.empty { color: var(--ink-2); margin: 12px 0 4px; }
.linkish { border: 0; background: none; padding: 0; font: inherit; color: var(--win); cursor: pointer;
           text-decoration: underline; }

/* ---- footer ---- */
footer { margin-top: 40px; background: var(--navy); color: #c9d3e3; font-size: 12.5px; border-top: 3px solid var(--red); }
.foot-in { display: grid; grid-template-columns: 2fr 1fr; gap: 24px; padding-top: 22px; padding-bottom: 26px; }
footer h5 { margin: 0 0 6px; color: #fff; font: 700 13px/1 "Roboto Condensed", "Arial Narrow", sans-serif;
            text-transform: uppercase; letter-spacing: .06em; }
footer p { margin: 0 0 8px; }
footer a { color: #fff; }

/* ---- responsive ---- */
@media (max-width: 960px) {
  .intro { grid-template-columns: 1fr; }
  .split { grid-template-columns: 1fr; gap: 0; }
}
@media (max-width: 700px) {
  .jump { display: none; }
  .hide-sm { display: none; }
  .foot-in { grid-template-columns: 1fr; }
  .topbar-meta .gh { display: none; }
}
@media (max-width: 520px) {
  h1 { font-size: 28px; }
  .brand-name { display: none; }
  .sb-grid { grid-template-columns: repeat(2, 1fr); }
  .sb-grid .sb-cell:nth-child(odd) { border-left: 0; }
  .sb-grid .sb-cell:nth-child(even) { border-left: 1px solid rgba(255,255,255,.12); }
  .hide-xs { display: none; }
  .stats td, .stats th { padding-left: 7px; padding-right: 7px; }
  .dist { min-width: 80px; }
  .tm { display: block; margin-left: 0; }
}
</style>
</head>
<body>
<header class="topbar">
  <div class="wrap topbar-in">
    <a class="brand" href="./" aria-label="Starter Game Value home">
      <span class="brand-mark">SGV</span><span class="brand-name">Starter Game Value</span>
    </a>
    <div class="topbar-meta">
      <span id="through"></span>
      <a class="gh" href="https://github.com/Luca-Pfi/Advanced-Sabermetrics-Development-SGV">GitHub</a>
    </div>
  </div>
</header>
<nav class="subnav" aria-label="Season and sections">
  <div class="wrap subnav-in">
    <div class="tabs" id="seasons" role="tablist" aria-label="Season"></div>
    <div class="jump">
      <a href="#leaders">Leaders</a><a href="#hard-luck">Hard Luck</a><a href="#fortunate">Fortunate</a><a href="#lookup">Player Search</a>
    </div>
  </div>
</nav>

<main>
  <section class="wrap intro">
    <div>
      <h1>Starter Game Value</h1>
      <p class="lede">A pitcher's win-loss record depends on run support and the bullpen. SGV gives every start
      a win, loss or no-decision on the pitching alone, against a league-average offense and bullpen, adjusted
      for the ballpark. A start is an SGV no-decision when it left the team a <span id="band"></span> chance to win.</p>
      <p class="formula" aria-label="SGV formula">SGV = (ER + Bullpen RA9 × (9 − IP) / 9) − (Runs per team game × Park factor)</p>
    </div>
    <div class="scoreboard" id="scoreboard" aria-live="polite"></div>
  </section>

  <section class="wrap block" id="leaders">
    <div class="block-head"><h2>SGV Leaders</h2><p class="block-note" id="qual"></p></div>
    <div class="table-wrap"><table class="stats" id="leaders-table"></table></div>
    <button class="more" id="leaders-more" type="button"></button>
  </section>

  <div class="wrap split">
    <section class="block" id="hard-luck">
      <div class="block-head"><h2>Hard Luck</h2><p class="block-note">Real record undersells the pitching</p></div>
      <p class="block-desc">Run support or the bullpen let them down. Swing = SGV net wins − real net wins.</p>
      <div class="key"><span><i class="ring"></i>Real</span><span><i class="fill" style="background:var(--win)"></i>SGV</span><span>net wins (W − L)</span></div>
      <div class="table-wrap"><table class="stats" id="hard-luck-table"></table></div>
    </section>
    <section class="block" id="fortunate">
      <div class="block-head"><h2>Fortunate</h2><p class="block-note">Real record flatters the pitching</p></div>
      <p class="block-desc">The offense or the bullpen bailed them out. Same scale as Hard Luck.</p>
      <div class="key"><span><i class="ring"></i>Real</span><span><i class="fill" style="background:var(--loss)"></i>SGV</span><span>net wins (W − L)</span></div>
      <div class="table-wrap"><table class="stats" id="fortunate-table"></table></div>
    </section>
  </div>

  <section class="wrap block" id="lookup">
    <div class="block-head"><h2 id="lookup-title">Player Search</h2><p class="block-note">Every starter, qualified or not</p></div>
    <div class="search">
      <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>
      <input id="search" type="search" placeholder="Search a pitcher" autocomplete="off"
             role="combobox" aria-expanded="false" aria-controls="matches" aria-autocomplete="list"
             aria-label="Search a pitcher">
      <ul id="matches" role="listbox" hidden></ul>
    </div>
    <div id="player"></div>
  </section>
</main>

<footer>
  <div class="wrap foot-in">
    <div>
      <h5>Method</h5>
      <p id="foot"></p>
      <p>Qualified: at least 1 start per 8 team games (20 GS over a full season). Swing = (SGV W − SGV L) − (real W − real L).</p>
    </div>
    <div>
      <h5>Data</h5>
      <p>Box scores: MLB Stats API. Park factors: FanGraphs.</p>
      <p><a href="sgv_records.xlsx">Download every start (.xlsx)</a> · <a href="https://github.com/Luca-Pfi/Advanced-Sabermetrics-Development-SGV">Code on GitHub</a></p>
      <p>Independent project. Not affiliated with or endorsed by Major League Baseball.</p>
    </div>
  </div>
</footer>

<script>
const DATA = __DATA__;
const META = __META__;
const NS = "http://www.w3.org/2000/svg";
const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const signed = (n) => (n > 0 ? "+" : n < 0 ? "−" : "") + Math.abs(n);
const dec2 = (n) => (n < 0 ? "−" : "") + Math.abs(n).toFixed(2);
const rec = (a) => `${a[0]}-${a[1]}`;
const net = (a) => a[0] - a[1];
const norm = (t) => t.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
const ipText = (outs) => `${Math.floor(outs / 3)}.${outs % 3}`;
const fmt = (n) => n.toLocaleString("en-US");
function el(tag, attrs = {}, text) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (text !== undefined) n.textContent = text;
  return n;
}

let current, selected = null, expanded = false, sort = { key: "rank", dir: 1 };
const seasonData = () => DATA.find((x) => x.season === current);

/* ---------- scoreboard ---------- */
function renderScoreboard(d) {
  const t = d.totals;
  const cell = (k, v, cls = "") => `<div class="sb-cell"><div class="sb-k">${k}</div><div class="sb-v ${cls}">${v}</div></div>`;
  const blend = d.currentWeight < 1 ? ` · early season, ${Math.round(d.currentWeight * 100)}% ${d.season} averages` : "";
  document.getElementById("scoreboard").innerHTML =
    `<div class="sb-head">${d.season} Season<span>${fmt(t.starts)} starts${blend}</span></div>
     <div class="sb-grid">
       ${cell("SGV W", fmt(t.W), "w")}${cell("SGV L", fmt(t.L), "l")}${cell("SGV ND", fmt(t.ND))}${cell("Qualified", d.qualified)}
       ${cell("W if SGV <", dec2(d.wCut))}${cell("L if SGV >", "+" + d.lCut.toFixed(2))}${cell("Lg R/G", d.rpg.toFixed(2))}${cell("Pen RA9", d.ra9.toFixed(2))}
     </div>`;
}

/* ---------- leaders table ---------- */
const LEAD_COLS = [
  { key: "rank", label: "Rk", cls: "rk", val: (r) => r.rank },
  { key: "name", label: "Player", cls: "l", val: (r) => norm(r.name), dir: 1 },
  { key: "gs", label: "GS", cls: "hide-xs", val: (r) => r.gs, dir: -1 },
  { key: "sgv", label: "SGV", val: (r) => net(r.sgv) * 1000 + r.sgv[0], dir: -1 },
  { key: "nd", label: "ND", cls: "hide-sm", val: (r) => r.sgv[2], dir: -1 },
  { key: "dist", label: "W · ND · L", cls: "l col-dist hide-xs" },
  { key: "real", label: "Real", val: (r) => net(r.act) * 1000 + r.act[0], dir: -1 },
  { key: "swing", label: "Swing", cls: "hide-sm", val: (r) => r.swing, dir: -1 },
  { key: "avg", label: "Avg SGV", cls: "hide-sm", val: (r) => r.avg, dir: 1 },
];
function playerLink(r) {
  return `<span class="player"><a href="#lookup" data-name="${esc(r.name)}">${esc(r.name)}</a></span><span class="tm">${esc(r.team)}</span>`;
}
function renderLeaders(d) {
  const col = LEAD_COLS.find((c) => c.key === sort.key);
  const rows = [...d.all].sort((a, b) => (col.val(a) > col.val(b) ? 1 : col.val(a) < col.val(b) ? -1 : a.rank - b.rank) * sort.dir);
  const shown = expanded ? rows : rows.slice(0, 10);
  const maxGs = Math.max(...d.all.map((r) => r.gs));
  const head = LEAD_COLS.map((c) => {
    const s = c.val ? ` class="sortable ${c.cls || ""}" data-key="${c.key}"` : ` class="${c.cls || ""}"`;
    const aria = c.key === sort.key ? ` aria-sort="${sort.dir === 1 ? "ascending" : "descending"}"` : "";
    return `<th scope="col"${s}${aria}>${c.label}</th>`;
  }).join("");
  const body = shown.map((r) => {
    const seg = (n, c, label) => n ? `<i style="width:${(n / maxGs) * 100}%;background:var(${c})" title="${n} SGV ${label}"></i>` : "";
    return `<tr>
      <td class="rk">${r.rank}</td>
      <td class="l">${playerLink(r)}</td>
      <td class="hide-xs">${r.gs}</td>
      <td class="rec">${rec(r.sgv)}</td>
      <td class="hide-sm">${r.sgv[2]}</td>
      <td class="l col-dist hide-xs"><div class="dist">${seg(r.sgv[0], "--win", "W")}${seg(r.sgv[2], "--nd", "ND")}${seg(r.sgv[1], "--loss", "L")}</div></td>
      <td>${rec(r.act)}</td>
      <td class="hide-sm"><span class="pill ${r.swing > 0 ? "pos" : r.swing < 0 ? "neg" : ""}">${signed(r.swing)}</span></td>
      <td class="hide-sm">${dec2(r.avg)}</td>
    </tr>`;
  }).join("");
  const table = document.getElementById("leaders-table");
  table.innerHTML = `<thead><tr>${head}</tr></thead><tbody>${body}</tbody>`;
  table.querySelectorAll("th.sortable").forEach((th) => th.addEventListener("click", () => {
    const c = LEAD_COLS.find((x) => x.key === th.dataset.key);
    sort = sort.key === c.key ? { key: c.key, dir: -sort.dir } : { key: c.key, dir: c.dir || 1 };
    renderLeaders(seasonData());
  }));
  const more = document.getElementById("leaders-more");
  more.hidden = d.all.length <= 10;
  more.textContent = expanded ? "Show top 10" : `Show all ${d.all.length} qualified`;
}
document.getElementById("leaders-more").addEventListener("click", () => {
  expanded = !expanded;
  renderLeaders(seasonData());
});

/* ---------- hard luck / fortunate ---------- */
// Drawn at the cell's real pixel width, so the dots stay round.
function dumbbell(r, lo, hi, color, width) {
  const w = Math.max(60, width), h = 22, pad = 6, sx = (v) => pad + (v - lo) / (hi - lo) * (w - 2 * pad);
  const svg = el("svg", { viewBox: `0 0 ${w} ${h}`, role: "img",
    "aria-label": `${r.name}: real ${rec(r.act)}, SGV ${rec(r.sgv)}` });
  svg.append(el("line", { x1: sx(0), x2: sx(0), y1: 2, y2: h - 2, stroke: "var(--line)", "stroke-width": 1.5 }));
  const a = sx(net(r.act)), b = sx(net(r.sgv));
  svg.append(el("line", { x1: a, x2: b, y1: h / 2, y2: h / 2, stroke: color, "stroke-width": 2.5, opacity: 0.45 }));
  const ring = el("circle", { cx: a, cy: h / 2, r: 4.5, fill: "var(--surface)", stroke: "var(--ink-3)", "stroke-width": 2 });
  ring.append(el("title", {}, `Real ${rec(r.act)} (${signed(net(r.act))} net)`));
  const dot = el("circle", { cx: b, cy: h / 2, r: 5, fill: color });
  dot.append(el("title", {}, `SGV ${rec(r.sgv)} (${signed(net(r.sgv))} net)`));
  svg.append(ring, dot);
  return svg;
}
function renderSwing(id, rows, lo, hi, color) {
  const table = document.getElementById(id);
  table.innerHTML = `<thead><tr><th class="rk">Rk</th><th class="l">Player</th><th>Real</th><th>SGV</th><th>Swing</th>
    <th class="l col-viz hide-xs">Real → SGV</th></tr></thead><tbody>${
    rows.map((r, i) => `<tr><td class="rk">${i + 1}</td><td class="l">${playerLink(r)}</td><td>${rec(r.act)}</td>
      <td class="rec">${rec(r.sgv)}</td><td><span class="pill ${r.swing > 0 ? "pos" : "neg"}">${signed(r.swing)}</span></td>
      <td class="l col-viz hide-xs"></td></tr>`).join("") ||
    `<tr><td colspan="6" class="l">No qualified starters yet.</td></tr>`}</tbody>`;
  table.querySelectorAll("td.col-viz").forEach((td, i) => {
    const cs = getComputedStyle(td);
    const width = td.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
    if (width > 0) td.append(dumbbell(rows[i], lo, hi, color, width));
  });
}

/* ---------- player search ---------- */
const searchBox = document.getElementById("search");
const matchList = document.getElementById("matches");
let matches = [], active = -1;
function showMatches() {
  const q = norm(searchBox.value.trim());
  matches = q ? seasonData().players.filter((p) => norm(p.n).includes(q))
    .sort((a, b) => norm(a.n).indexOf(q) - norm(b.n).indexOf(q) || b.g.length - a.g.length).slice(0, 8) : [];
  active = matches.length ? 0 : -1;
  matchList.innerHTML = matches.length
    ? matches.map((p, i) => `<li role="option" id="m${i}" aria-selected="${i === active}" data-i="${i}">` +
        `${esc(p.n)}<span>${esc(p.t)} · ${p.g.length} GS</span></li>`).join("")
    : (q ? `<li aria-disabled="true">No starter matching “${esc(searchBox.value.trim())}” in ${current}</li>` : "");
  matchList.hidden = !q;
  searchBox.setAttribute("aria-expanded", String(!!q));
}
function choose(p) {
  selected = p.id;
  searchBox.value = p.n;
  matchList.hidden = true;
  searchBox.setAttribute("aria-expanded", "false");
  history.replaceState(null, "", `#pitcher=${encodeURIComponent(p.n)}&season=${current}`);
  renderLookup();
}
searchBox.addEventListener("input", showMatches);
searchBox.addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    if (!matches.length) return;
    e.preventDefault();
    active = (active + (e.key === "ArrowDown" ? 1 : matches.length - 1)) % matches.length;
    matchList.querySelectorAll("li").forEach((li, i) => li.setAttribute("aria-selected", String(i === active)));
  } else if (e.key === "Enter" && active >= 0) {
    e.preventDefault(); choose(matches[active]);
  } else if (e.key === "Escape") {
    matchList.hidden = true;
  }
});
matchList.addEventListener("mousedown", (e) => {
  const li = e.target.closest("li[data-i]");
  if (li) { e.preventDefault(); choose(matches[+li.dataset.i]); }
});
searchBox.addEventListener("blur", () => { matchList.hidden = true; });
// A player name in any table opens that player in the search.
document.addEventListener("click", (e) => {
  const a = e.target.closest("a[data-name]");
  if (!a) return;
  const p = seasonData().players.find((x) => x.n === a.dataset.name);
  if (!p) return;
  e.preventDefault();   // keep the #pitcher= link instead of jumping to #lookup
  choose(p);
  document.getElementById("lookup").scrollIntoView();
});

// SGV of every start; negative (good) drawn upward, dashed lines at the season's W and L cut-offs.
function startChart(p, d, width) {
  const w = Math.max(300, width), h = 150, x0 = 30, y0 = 8, plotH = 128;
  const vals = p.g.map((g) => g[5]);
  const top = Math.min(-3, Math.floor(Math.min(...vals, d.wCut))), bot = Math.max(3, Math.ceil(Math.max(...vals, d.lCut)));
  const sy = (v) => y0 + (v - top) / (bot - top) * plotH;
  const band = (w - x0 - 4) / p.g.length, bw = Math.max(2, Math.min(16, band - 2));
  const svg = el("svg", { viewBox: `0 0 ${w} ${h}`, role: "img", "aria-label": `SGV of each ${p.n} start in ${d.season}` });
  for (let v = top; v <= bot; v++) {
    if (v % 2) continue;
    svg.append(el("line", { x1: x0, x2: w, y1: sy(v), y2: sy(v), stroke: v === 0 ? "var(--ink-3)" : "var(--line-soft)" }));
    svg.append(el("text", { x: x0 - 6, y: sy(v) + 4, class: "axis", "text-anchor": "end" }, v === 0 ? "0" : signed(v)));
  }
  [[d.wCut, "var(--win)"], [d.lCut, "var(--loss)"]].forEach(([v, c]) =>
    svg.append(el("line", { x1: x0, x2: w, y1: sy(v), y2: sy(v), stroke: c, "stroke-dasharray": "4 4", opacity: 0.8 })));
  p.g.forEach((g, i) => {
    const [date, opp, ha, outs, er, sgv, dec, act] = g;
    const x = x0 + i * band + (band - bw) / 2, ya = sy(0), yb = sy(sgv);
    const r = el("rect", { x, y: Math.min(ya, yb), width: bw, height: Math.max(1, Math.abs(yb - ya)), rx: 1.5,
      fill: dec === "W" ? "var(--win)" : dec === "L" ? "var(--loss)" : "var(--nd)" });
    r.append(el("title", {}, `${date} ${ha === "H" ? "vs" : "@"} ${opp}: ${ipText(outs)} IP, ${er} ER, ` +
      `SGV ${dec2(sgv)} (SGV ${dec}, real ${act})`));
    svg.append(r);
  });
  return svg;
}
function renderLookup() {
  const d = seasonData(), box = document.getElementById("player");
  document.getElementById("lookup-title").textContent = `Player Search · ${current}`;
  if (selected === null) { box.replaceChildren(); return; }
  const p = d.players.find((x) => x.id === selected);
  if (!p) {
    const other = DATA.filter((x) => x.season !== current && x.players.some((y) => y.id === selected));
    const name = DATA.flatMap((x) => x.players).find((y) => y.id === selected).n;
    box.innerHTML = `<p class="empty">${esc(name)} made no starts in ${current}.` +
      other.map((x) => ` <button class="linkish" data-season="${x.season}">See ${x.season}</button>`).join("") + "</p>";
    box.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => renderSeason(+b.dataset.season)));
    return;
  }
  const swing = net(p.s) - net(p.a);
  const era = p.outs ? (27 * p.er / p.outs).toFixed(2) : "–";
  const stat = (k, v, s = "") => `<div><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s || "&nbsp;"}</div></div>`;
  box.innerHTML = `<div class="pcard">
    <div class="pcard-head"><h3>${esc(p.n)}</h3><span>${esc(p.t)} · ${current}${p.rank ? ` · SGV rank #${p.rank} of ${d.qualified}` : ` · not qualified (${d.qualifier} GS)`}</span></div>
    <div class="statline">
      ${stat("SGV", rec(p.s), `${p.s[2]} ND`)}
      ${stat("Real", rec(p.a), `${p.a[2]} ND`)}
      ${stat("Swing", signed(swing), "net wins")}
      ${stat("Avg SGV", dec2(p.avg))}
      ${stat("GS", p.g.length, `${ipText(p.outs)} IP`)}
      ${stat("ERA", era, `${p.er} ER`)}
    </div>
    <div class="pcard-body"><h4>SGV by start</h4><div id="start-chart"></div>
      <p class="note">Each bar is one start, in order. Above 0 is better than average; dashed lines mark the SGV W (${dec2(d.wCut)}) and SGV L (+${d.lCut.toFixed(2)}) cut-offs. Hover a bar for the line.</p>
      <details class="log"><summary>Game log · ${p.g.length} starts</summary><div class="table-wrap"><table class="stats"><thead><tr>
        <th class="l">Date</th><th class="l">Opp</th><th>IP</th><th>ER</th><th>SGV</th><th>SGV Dec</th><th>Real Dec</th><th class="hide-xs">Team</th>
        </tr></thead><tbody>${p.g.map(([date, opp, ha, outs, er, sgv, dec, act, res]) => `<tr><td class="l">${date}</td>
        <td class="l">${ha === "H" ? "vs" : "@"} ${esc(opp)}</td><td>${ipText(outs)}</td><td>${er}</td><td>${dec2(sgv)}</td>
        <td><span class="dec dec-${dec}">${dec}</span></td><td>${act}</td><td class="hide-xs">${res}</td></tr>`).join("")}
        </tbody></table></div></details>
    </div></div>`;
  const holder = document.getElementById("start-chart");
  holder.append(startChart(p, d, Math.round(holder.clientWidth)));
}

/* ---------- season ---------- */
function renderSeason(season) {
  current = season;
  const d = seasonData();
  document.querySelectorAll("#seasons button").forEach((b) =>
    b.setAttribute("aria-selected", String(+b.dataset.season === season)));
  document.getElementById("band").textContent = d.band;
  document.getElementById("qual").textContent = `${d.season} · ${d.qualified} qualified starters, min. ${d.qualifier} GS`;
  renderScoreboard(d);
  renderLeaders(d);
  const vals = [...d.hardLuck, ...d.fortunate].flatMap((r) => [net(r.act), net(r.sgv)]);
  const lo = Math.min(-5, Math.floor(Math.min(...vals, 0) / 5) * 5), hi = Math.max(5, Math.ceil(Math.max(...vals, 0) / 5) * 5);
  renderSwing("hard-luck-table", d.hardLuck, lo, hi, "var(--win)");
  renderSwing("fortunate-table", d.fortunate, lo, hi, "var(--loss)");
  const blend = d.currentWeight < 1
    ? `Early season: league averages are ${Math.round(d.currentWeight * 100)}% ${season} and ` +
      `${Math.round((1 - d.currentWeight) * 100)}% ${season - 1} until ${season} has enough games. ` : "";
  document.getElementById("foot").textContent = blend +
    `${season}: SGV W if SGV < ${dec2(d.wCut)}, SGV L if SGV > +${d.lCut.toFixed(2)}, SGV ND in between ` +
    `(team win probability ${d.band}). Thresholds are fixed for the season, calibrated on ${d.calibratedOn}. ` +
    `League bullpen RA9 ${d.ra9.toFixed(2)}, ${d.rpg.toFixed(2)} runs per team game.`;
  renderLookup();
  try { localStorage.setItem("sgv-season", season); } catch (e) {}
}

const tabs = document.getElementById("seasons");
[...DATA].reverse().forEach((d) => {
  const b = document.createElement("button");
  b.type = "button"; b.setAttribute("role", "tab"); b.textContent = d.season; b.dataset.season = d.season;
  b.addEventListener("click", () => renderSeason(d.season));
  tabs.append(b);
});
document.getElementById("through").textContent = "Through " +
  new Date(META.through + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });

let start = DATA[DATA.length - 1].season;
try { const s = +localStorage.getItem("sgv-season"); if (DATA.some((d) => d.season === s)) start = s; } catch (e) {}
// A shared lookup link: #pitcher=<name>&season=<year>
const hash = new URLSearchParams(location.hash.slice(1));
if (hash.get("season") && DATA.some((d) => d.season === +hash.get("season"))) start = +hash.get("season");
if (hash.get("pitcher")) {
  const want = norm(hash.get("pitcher"));
  const hit = (DATA.find((d) => d.season === start) || DATA.at(-1)).players.find((p) => norm(p.n) === want)
    || DATA.flatMap((d) => d.players).find((p) => norm(p.n) === want);
  if (hit) { selected = hit.id; searchBox.value = hit.n; }
}
renderSeason(start);
if (hash.get("pitcher")) document.getElementById("lookup").scrollIntoView();
let resizeTimer;
addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => renderSeason(current), 150); });
</script>
</body>
</html>
"""
