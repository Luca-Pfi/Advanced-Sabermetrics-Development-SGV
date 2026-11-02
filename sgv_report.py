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


def write_report(df, league_rows, thresholds, path, photos=None):
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
            "lgAvg": round(float(starts["SGV"].mean()), 3),
            "totals": {"starts": len(starts),
                       **{d: int((starts["SGV_dec"] == d).sum()) for d in ("W", "L", "ND")}},
            "players": season_pitchers(df, int(s), board["qualifier"]),
        })
        data.append(board)
    meta = {"through": str(df["date"].max())}   # last game in the data, not the run time
    # Player photos for the starters on the page: id -> [thumbnail, file page, author, licence]
    ids = {str(i) for i in df["pitcher_id"].unique()}
    meta["photos"] = {pid: [p["img"], p["page"], p["artist"], p["license"]]
                      for pid, p in sorted((photos or {}).items()) if pid in ids and p.get("img")}
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
<link href="https://fonts.googleapis.com/css2?family=Roboto+Condensed:wght@400;700&display=swap" rel="stylesheet">
<style>
:root {
  color-scheme: light;
  --page: #ffffff; --panel: #ffffff; --head: #0f2a3a;
  --border: #4499aa; --rule: #399098; --dash: #8fc3cc; --track: #c7dcdc;
  --ink: #000000; --ink-2: #333333; --ink-3: #666666; --ink-4: #8a8a8a;
  --line: #d6d6d6; --row: #f5f5f5; --total: #c2c2c2; --link: #1f5f99;
  --w: #d82129; --nd: #b4cfd1; --l: #4e70b3; --roll: #c34444; --lg: #888888;
  --w-tint: #f8dcdd; --l-tint: #dfe6f3;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --page: #0d1316; --panel: #141c20; --head: #08171f;
    --border: #2f7f8c; --rule: #3a9aa6; --dash: #2a5f68; --track: #2b3b3f;
    --ink: #f2f6f7; --ink-2: #dce4e6; --ink-3: #a7b4b8; --ink-4: #7d8a8e;
    --line: #2b373b; --row: #182327; --total: #2c3a3f; --link: #7fb6e8;
    --w: #e0393f; --nd: #9fb9bc; --l: #5b80c4; --roll: #ef6a6a; --lg: #8d999c;
    --w-tint: #4a1d22; --l-tint: #1f2c47;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0d1316; --panel: #141c20; --head: #08171f;
  --border: #2f7f8c; --rule: #3a9aa6; --dash: #2a5f68; --track: #2b3b3f;
  --ink: #f2f6f7; --ink-2: #dce4e6; --ink-3: #a7b4b8; --ink-4: #7d8a8e;
  --line: #2b373b; --row: #182327; --total: #2c3a3f; --link: #7fb6e8;
  --w: #e0393f; --nd: #9fb9bc; --l: #5b80c4; --roll: #ef6a6a; --lg: #8d999c;
  --w-tint: #4a1d22; --l-tint: #1f2c47;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; scroll-padding-top: 56px; }
body { margin: 0; background: var(--page); color: var(--ink-2);
       font: 15px/1.4 "Roboto Condensed", "Arial Narrow", Roboto, Arial, sans-serif; }
a { color: var(--link); text-decoration: none; }
a:hover { text-decoration: underline; }
.wrap { max-width: 1240px; margin: 0 auto; padding: 0 16px; }
.num, table { font-variant-numeric: tabular-nums; }

/* top bar + season tabs */
.topbar { background: var(--head); color: #fff; border-bottom: 3px solid var(--border); }
.topbar-in { display: flex; align-items: center; justify-content: space-between; gap: 16px; height: 50px; }
.brand { display: flex; align-items: baseline; gap: 10px; color: #fff; }
.brand:hover { text-decoration: none; }
.brand b { font-size: 24px; letter-spacing: .02em; }
.brand span { font-size: 16px; color: #b9d3d8; }
.topbar-meta { display: flex; gap: 18px; font-size: 14px; color: #b9d3d8; }
.topbar-meta a { color: #fff; }
.subnav { background: var(--panel); border-bottom: 1px solid var(--line); position: sticky; top: 0; z-index: 20; }
.subnav-in { display: flex; justify-content: space-between; align-items: stretch; gap: 16px; }
.tabs { display: flex; }
.tabs button { border: 0; background: none; cursor: pointer; padding: 12px 16px 9px; font-family: inherit;
               font-size: 18px; font-weight: 700; line-height: 1; color: var(--ink-3); border-bottom: 3px solid transparent; }
.tabs button[aria-selected="true"] { color: var(--ink); border-bottom-color: var(--border); }
.jump { display: flex; align-items: center; gap: 18px; font-size: 15px; }
.jump a { color: var(--ink-3); }

/* Savant-style panels */
.panel { background: var(--panel); border: 1px solid var(--border); padding: 14px 18px 18px; min-width: 0; }
.ptitle { text-align: center; font-weight: 400; font-size: 26px; color: var(--ink); margin: 4px 0 16px; line-height: 1.25; }
.ptitle b { font-weight: 700; display: inline-block; padding-bottom: 3px; border-bottom: 3px dotted var(--border); }
.psub { text-align: center; color: var(--ink-3); margin: -10px 0 14px; font-size: 14px; }
.phead { display: flex; align-items: flex-end; gap: 8px; font-size: 22px; font-weight: 700; color: var(--ink);
         border-bottom: 3px solid var(--rule); padding-bottom: 3px; margin: 12px 0 6px; }
.phead svg { width: 22px; height: 22px; margin-bottom: 3px; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
section { margin-top: 18px; }

/* intro */
.intro { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 16px; margin-top: 18px; }
.intro h1 { font-size: 34px; font-weight: 700; color: var(--ink); margin: 2px 0 8px; }
.intro p { margin: 0 0 12px; font-size: 16px; color: var(--ink-2); }
.formula { padding: 8px 12px; border-left: 3px solid var(--rule); background: var(--row);
           font: 14px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; overflow-wrap: break-word; }

/* tables */
table.t { width: 100%; border-collapse: collapse; font-size: 15px; }
.t th { font-weight: 700; color: var(--ink); text-align: right; padding: 6px 8px; border-bottom: 1px solid var(--ink-2);
        white-space: nowrap; }
.t td { text-align: right; padding: 5px 8px; white-space: nowrap; color: var(--ink-2); }
.t tbody tr { border-bottom: 1px solid var(--line); }
.t tbody tr:hover td { background: var(--row); }
.t .l { text-align: left; }
.t .rk { width: 34px; color: var(--ink-3); }
.t tr.total td { background: var(--total); font-weight: 700; color: var(--ink); }
.t th.sortable { cursor: pointer; user-select: none; }
.t th.sortable:hover { color: var(--link); }
.t th[aria-sort="ascending"]::after { content: " ▲"; font-size: 10px; color: var(--border); }
.t th[aria-sort="descending"]::after { content: " ▼"; font-size: 10px; color: var(--border); }
.tm { color: var(--ink-4); margin-left: 5px; font-size: 13px; }
.rec { font-weight: 700; color: var(--ink); }
.scroll { overflow-x: auto; }
.pct { display: inline-block; min-width: 46px; padding: 1px 6px; border-radius: 12px; text-align: center;
       color: #fff; font-weight: 700; }
.swing { font-weight: 700; }
.swing.pos { color: var(--w); } .swing.neg { color: var(--l); }
.dist { display: flex; gap: 1px; height: 14px; min-width: 150px; }
.dist i { display: block; height: 100%; }
.viz svg { display: block; width: 100%; height: 22px; }
.viz { width: 34%; }
.btn { margin-top: 12px; border: 1px solid var(--border); background: var(--panel); color: var(--rule);
       font-family: inherit; font-size: 14px; font-weight: 700; line-height: 1; text-transform: uppercase; letter-spacing: .04em;
       padding: 9px 14px; cursor: pointer; }
.btn:hover { background: var(--border); color: #fff; }
.key { display: flex; justify-content: center; gap: 16px; flex-wrap: wrap; font-size: 13.5px; color: var(--ink-3);
       margin: -6px 0 10px; }
.key span { display: inline-flex; align-items: center; gap: 5px; }
.dot { width: 11px; height: 11px; border-radius: 50%; display: inline-block; border: 1px solid rgba(0,0,0,.55); }
.ring { width: 11px; height: 11px; border-radius: 50%; display: inline-block; border: 2px solid var(--ink-4); }
.sq { width: 11px; height: 11px; display: inline-block; }

/* league summary */
.league .t td { font-size: 22px; font-weight: 700; color: var(--ink); text-align: center; padding: 8px 4px 2px; }
.league .t th { text-align: center; font-size: 13px; color: var(--ink-3); border-bottom-color: var(--line); }
.league .t tbody tr { border: 0; }
.league .t td.w { color: var(--w); } .league .t td.lo { color: var(--l); }
.league .meta { text-align: center; color: var(--ink-3); font-size: 13.5px; margin: 10px 0 0; }
.league .split { display: flex; gap: 2px; height: 16px; margin: 16px 0 4px; }
.league .split i { display: block; height: 100%; }
.league .split-lbl { display: flex; justify-content: space-between; font-size: 13.5px; color: var(--ink-3); }

/* player search */
.search { position: relative; max-width: 480px; margin: 0 auto 16px; }
.search input { width: 100%; padding: 10px 12px 10px 38px; font-family: inherit; font-size: 16px; color: var(--ink);
                background: var(--panel); border: 1px solid var(--border); border-radius: 0; }
.search input:focus { outline: 2px solid var(--rule); outline-offset: 0; }
.search > svg { position: absolute; left: 12px; top: 50%; transform: translateY(-50%); width: 17px; height: 17px;
                stroke: var(--rule); fill: none; stroke-width: 2.2; pointer-events: none; }
.search ul { position: absolute; z-index: 30; left: 0; right: 0; top: calc(100% + 1px); margin: 0; padding: 0;
             list-style: none; background: var(--panel); border: 1px solid var(--border);
             box-shadow: 0 8px 20px rgba(0,0,0,.12); max-height: 300px; overflow-y: auto; }
.search li { padding: 8px 12px; cursor: pointer; display: flex; justify-content: space-between; gap: 12px;
             border-bottom: 1px solid var(--line); color: var(--ink); }
.search li span { color: var(--ink-3); font-size: 14px; }
.search li[aria-selected="true"], .search li:hover { background: var(--row); }
.pgrid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }
.card-top { text-align: center; }
.avatar img { width: 100%; height: 100%; border-radius: 50%; object-fit: cover; object-position: 50% 20%; display: block; }
.credit { font-size: 12px; color: var(--ink-4); margin: 6px 0 0; }
.credit a { color: var(--ink-3); text-decoration: underline; }
.avatar { width: 92px; height: 92px; margin: 4px auto 8px; border-radius: 50%; border: 3px solid var(--border); overflow: hidden;
          background: var(--row); color: var(--rule); display: grid; place-items: center; font-size: 34px; font-weight: 700; }
.pname { font-size: 36px; color: var(--ink); margin: 0; line-height: 1.1; }
.pline { font-size: 19px; color: var(--ink-2); margin: 4px 0 2px; }
.pline2 { font-size: 15px; color: var(--ink-3); margin: 0 0 14px; }
.card .t { font-size: 14px; }
.card .t th, .card .t td { padding: 4px 5px; }
.note { color: var(--ink-3); font-size: 13.5px; margin: 10px 0 0; }

/* percentile rankings */
.plegend, .prow { display: grid; grid-template-columns: 128px minmax(0, 1fr) 54px; column-gap: 10px; align-items: center; }
.plegend { margin: 8px 0 2px; font-size: 14px; }
.plegend .scale { position: relative; height: 30px; margin: 0 14px; }
.plegend .scale span { position: absolute; top: 0; transform: translateX(-50%); text-transform: uppercase;
                       letter-spacing: .02em; }
.plegend .scale span::after { content: "▲"; position: absolute; left: 50%; top: 17px; transform: translateX(-50%); font-size: 9px; }
.plegend .poor { left: 0; color: var(--l); } .plegend .avg { left: 50%; color: var(--ink-4); } .plegend .great { left: 100%; color: var(--w); }
.prow { height: 35px; }
.prow .lab { text-align: right; color: var(--ink-3); font-size: 15.5px; border-bottom: 1px dashed var(--dash);
             height: 100%; display: flex; align-items: center; justify-content: flex-end; white-space: nowrap; }
.prow .val { text-align: right; color: var(--ink-3); font-size: 15.5px; border-bottom: 1px dashed var(--dash);
             height: 100%; display: flex; align-items: center; justify-content: flex-end; }
.pbar { position: relative; height: 28px; margin: 0 14px; }
.pbar .trk { position: absolute; left: 0; right: 0; top: 50%; height: 6px; transform: translateY(-50%); background: var(--track); }
.pbar .fil { position: absolute; left: 0; top: 0; bottom: 0; }
.pbar .mid { position: absolute; left: 50%; top: 0; bottom: 0; width: 2px; margin-left: -1px; background: var(--panel); opacity: .9; }
.pbar .bdg { position: absolute; top: 50%; width: 27px; height: 27px; transform: translate(-50%, -50%); border-radius: 50%;
             border: 2px solid var(--panel); color: #fff; font-weight: 700; font-size: 14px; display: grid; place-items: center;
             box-shadow: 0 0 0 1px rgba(0,0,0,.08); }
.unq { color: var(--ink-3); font-size: 13.5px; text-align: center; margin: 2px 0 6px; }

/* charts */
.chart svg { display: block; width: 100%; height: auto; }
.axis { fill: var(--ink-3); font-size: 12.5px; font-family: "Roboto Condensed", Arial, sans-serif; }
.lbl { fill: var(--ink-3); font-size: 12px; font-family: "Roboto Condensed", Arial, sans-serif; }
.dec { display: inline-block; min-width: 30px; padding: 0 5px; text-align: center; font-weight: 700; font-size: 13px; color: #fff; }
.dec-W { background: var(--w); } .dec-L { background: var(--l); } .dec-ND { background: var(--nd); color: #10272c; }
details.log summary { cursor: pointer; text-align: center; color: var(--rule); font-weight: 700; text-transform: uppercase;
                      letter-spacing: .04em; padding: 6px 0 10px; }
.empty { color: var(--ink-2); text-align: center; margin: 10px 0; }
.linkish { border: 0; background: none; padding: 0; font: inherit; color: var(--link); cursor: pointer; text-decoration: underline; }

/* footer */
footer { margin-top: 28px; border-top: 3px solid var(--border); background: var(--head); color: #b9d3d8; font-size: 14px; }
.foot-in { display: grid; grid-template-columns: 2fr 1fr; gap: 24px; padding-top: 18px; padding-bottom: 22px; }
footer h5 { margin: 0 0 6px; color: #fff; font-size: 15px; text-transform: uppercase; letter-spacing: .05em; }
footer p { margin: 0 0 8px; }
footer a { color: #fff; text-decoration: underline; }

@media (max-width: 1100px) {
  .pgrid { grid-template-columns: 1fr 1fr; }
  .pgrid .roll { grid-column: 1 / -1; }
}
@media (max-width: 860px) {
  .intro, .grid2, .pgrid, .foot-in { grid-template-columns: 1fr; }
  .jump { display: none; }
  .hide-md { display: none; }
}
@media (max-width: 520px) {
  .brand span, .topbar-meta .gh { display: none; }
  .hide-sm { display: none; }
  .panel { padding: 12px 10px 14px; }
  .ptitle { font-size: 22px; }
  .t th, .t td { padding-left: 5px; padding-right: 5px; }
  .tm { display: block; margin-left: 0; }
  .plegend, .prow { grid-template-columns: 104px minmax(0, 1fr) 46px; column-gap: 6px; }
  .prow .lab, .prow .val { font-size: 14px; }
  .league .t td { font-size: 18px; }
}
</style>
</head>
<body>
<header class="topbar">
  <div class="wrap topbar-in">
    <a class="brand" href="./"><b>SGV</b><span>Starter Game Value</span></a>
    <div class="topbar-meta"><span id="through"></span>
      <a class="gh" href="https://github.com/Luca-Pfi/Advanced-Sabermetrics-Development-SGV">GitHub</a></div>
  </div>
</header>
<nav class="subnav" aria-label="Season and sections">
  <div class="wrap subnav-in">
    <div class="tabs" id="seasons" role="tablist" aria-label="Season"></div>
    <div class="jump"><a href="#leaders">Leaders</a><a href="#hard-luck">Hard Luck</a><a href="#fortunate">Fortunate</a><a href="#lookup">Player Search</a></div>
  </div>
</nav>

<main class="wrap">
  <div class="intro">
    <div class="panel">
      <h1>Starter Game Value</h1>
      <p>A pitcher's win-loss record depends on run support and the bullpen. SGV gives every start a win, loss or
      no-decision on the pitching alone, against a league-average offense and bullpen, adjusted for the ballpark.
      A start is an SGV no-decision when it left the team a <span id="band"></span> chance to win.</p>
      <p class="formula" aria-label="SGV formula">SGV = (ER + Bullpen RA9 × (9 − IP) / 9) − (Runs per team game × Park factor)</p>
    </div>
    <div class="panel league" id="scoreboard"></div>
  </div>

  <section class="panel" id="leaders">
    <h2 class="ptitle"><b class="yr"></b> SGV Leaders</h2>
    <p class="psub" id="qual"></p>
    <div class="key"><span><i class="sq" style="background:var(--w)"></i>SGV W</span><span><i class="sq" style="background:var(--nd)"></i>SGV ND</span><span><i class="sq" style="background:var(--l)"></i>SGV L</span><span>Avg SGV badge: percentile among qualified starters</span></div>
    <div class="scroll"><table class="t" id="leaders-table"></table></div>
    <div style="text-align:center"><button class="btn" id="leaders-more" type="button"></button></div>
  </section>

  <div class="grid2">
    <section class="panel" id="hard-luck">
      <h2 class="ptitle"><b class="yr"></b> Hard Luck</h2>
      <p class="psub">Pitched better than the real record shows</p>
      <div class="key"><span><i class="ring"></i>Real</span><span><i class="dot" style="background:var(--w)"></i>SGV</span><span>net wins (W − L)</span></div>
      <div class="scroll"><table class="t" id="hard-luck-table"></table></div>
    </section>
    <section class="panel" id="fortunate">
      <h2 class="ptitle"><b class="yr"></b> Fortunate</h2>
      <p class="psub">Real record flatters the pitching</p>
      <div class="key"><span><i class="ring"></i>Real</span><span><i class="dot" style="background:var(--l)"></i>SGV</span><span>same scale as Hard Luck</span></div>
      <div class="scroll"><table class="t" id="fortunate-table"></table></div>
    </section>
  </div>

  <section id="lookup">
    <div class="panel" style="padding-bottom:6px">
      <h2 class="ptitle" id="lookup-title"><b class="yr"></b> Player Search</h2>
      <div class="search">
        <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>
        <input id="search" type="search" placeholder="Search any starter" autocomplete="off"
               role="combobox" aria-expanded="false" aria-controls="matches" aria-autocomplete="list" aria-label="Search a pitcher">
        <ul id="matches" role="listbox" hidden></ul>
      </div>
      <p class="psub" style="margin:0 0 8px">Type a name to see a pitcher's SGV profile, percentile rankings and game log.</p>
    </div>
    <div id="player"></div>
  </section>
</main>

<footer>
  <div class="wrap foot-in">
    <div><h5>Method</h5><p id="foot"></p>
      <p>Qualified: at least 1 start per 8 team games (20 GS over a full season). Swing = (SGV W − SGV L) − (real W − real L).
      Percentiles rank qualified starters of the season, 1 to 100; for Avg SGV, ERA, SGV Loss % and Short Start %, lower is better.</p></div>
    <div><h5>Data</h5><p>Box scores: MLB Stats API. Park factors: FanGraphs.</p>
      <p><a href="sgv_records.xlsx">Download every start (.xlsx)</a> · <a href="https://github.com/Luca-Pfi/Advanced-Sabermetrics-Development-SGV">Code on GitHub</a></p>
      <p>Independent project. Not affiliated with or endorsed by Major League Baseball.</p></div>
  </div>
</footer>

<script>
const DATA = __DATA__;
const META = __META__;
const NS = "http://www.w3.org/2000/svg";
const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const signed = (n) => (n > 0 ? "+" : n < 0 ? "−" : "") + Math.abs(n);
const dec2 = (n) => (n < 0 ? "−" : n > 0 ? "" : "") + Math.abs(n).toFixed(2);
const rec = (a) => `${a[0]}-${a[1]}`;
const net = (a) => a[0] - a[1];
const norm = (t) => t.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
const ipText = (outs) => `${Math.floor(outs / 3)}.${outs % 3}`;
const fmt = (n) => n.toLocaleString("en-US");
const pctText = (x) => `${Math.round(x * 100)}%`;
function el(tag, attrs = {}, text) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (text !== undefined) n.textContent = text;
  return n;
}
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

// Percentile colour scale sampled from Savant's percentile bars: blue (poor) - grey-teal (average) - red (great).
const STOPS = [[1, "#3d61ad"], [11, "#4e70b3"], [27, "#809bc1"], [50, "#b4cfd1"], [68, "#cea197"],
               [80, "#d77364"], [84, "#d96254"], [91, "#d93f38"], [96, "#d82129"], [100, "#d82129"]];
function pctColor(p) {
  const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  for (let i = 1; i < STOPS.length; i++) {
    const [p1, c1] = STOPS[i - 1], [p2, c2] = STOPS[i];
    if (p <= p2) {
      const t = (p - p1) / (p2 - p1 || 1), a = hex(c1), b = hex(c2);
      return `rgb(${a.map((v, k) => Math.round(v + (b[k] - v) * t)).join(",")})`;
    }
  }
  return STOPS.at(-1)[1];
}

let current, selected = null, expanded = false, sort = { key: "rank", dir: 1 };
const seasonData = () => DATA.find((x) => x.season === current);

/* ---------- metrics + percentiles ---------- */
const QS = (g) => g[3] >= 18 && g[4] <= 3;          // quality start: 6+ IP, 3 or fewer ER
const SHORT = (g) => g[3] < 15;                      // fewer than 5 IP
const METRICS = [
  { group: "SGV", key: "avg", label: "Avg SGV", better: -1, get: (p) => p.avg, show: (v) => dec2(v) },
  { group: "SGV", key: "winp", label: "SGV Win %", better: 1, get: (p) => p.s[0] / p.g.length, show: pctText },
  { group: "SGV", key: "lossp", label: "SGV Loss %", better: -1, get: (p) => p.s[1] / p.g.length, show: pctText },
  { group: "SGV", key: "net", label: "SGV W − L", better: 1, get: (p) => net(p.s), show: signed },
  { group: "Pitching", key: "era", label: "ERA", better: -1, get: (p) => (p.outs ? 27 * p.er / p.outs : 99), show: (v) => v.toFixed(2) },
  { group: "Pitching", key: "ipgs", label: "IP / Start", better: 1, get: (p) => p.outs / 3 / p.g.length, show: (v) => v.toFixed(1) },
  { group: "Pitching", key: "qs", label: "Quality Start %", better: 1, get: (p) => p.g.filter(QS).length / p.g.length, show: pctText },
  { group: "Pitching", key: "short", label: "Short Start %", better: -1, get: (p) => p.g.filter(SHORT).length / p.g.length, show: pctText },
];
const poolCache = new Map();
function pool(d, m) {
  const k = `${d.season}:${m.key}`;
  if (!poolCache.has(k)) poolCache.set(k, d.players.filter((p) => p.q).map(m.get));
  return poolCache.get(k);
}
function percentile(d, m, v) {
  const vals = pool(d, m);
  if (!vals.length) return 50;
  let worse = 0, same = 0;
  for (const x of vals) { if (x === v) same++; else if ((x - v) * m.better < 0) worse++; }
  return Math.max(1, Math.min(100, Math.round(100 * (worse + 0.5 * same) / vals.length)));
}

/* ---------- league panel ---------- */
function renderScoreboard(d) {
  const t = d.totals;
  const blend = d.currentWeight < 1 ? ` Early season: league averages are ${Math.round(d.currentWeight * 100)}% ${d.season}.` : "";
  document.getElementById("scoreboard").innerHTML =
    `<h2 class="ptitle"><b>${d.season}</b> League</h2>
     <div class="scroll"><table class="t"><thead><tr><th>Starts</th><th>SGV W</th><th>SGV L</th><th>SGV ND</th>
       <th class="hide-sm">W if SGV &lt;</th><th class="hide-sm">L if SGV &gt;</th></tr></thead>
     <tbody><tr><td>${fmt(t.starts)}</td><td class="w">${fmt(t.W)}</td><td class="lo">${fmt(t.L)}</td><td>${fmt(t.ND)}</td>
       <td class="hide-sm">${dec2(d.wCut)}</td><td class="hide-sm">+${d.lCut.toFixed(2)}</td></tr></tbody></table></div>
     <div class="split" role="img" aria-label="Share of starts: SGV W ${pctText(t.W / t.starts)}, ND ${pctText(t.ND / t.starts)}, SGV L ${pctText(t.L / t.starts)}">
       <i style="width:${100 * t.W / t.starts}%;background:var(--w)"></i><i style="width:${100 * t.ND / t.starts}%;background:var(--nd)"></i><i style="width:${100 * t.L / t.starts}%;background:var(--l)"></i></div>
     <div class="split-lbl"><span>SGV W ${pctText(t.W / t.starts)}</span><span>ND ${pctText(t.ND / t.starts)}</span><span>SGV L ${pctText(t.L / t.starts)}</span></div>
     <p class="meta">League ${d.rpg.toFixed(2)} runs per team game · bullpen RA9 ${d.ra9.toFixed(2)} · average start SGV ${dec2(d.lgAvg)} ·
       ${d.qualified} qualified starters.${blend}</p>`;
}

/* ---------- leaders ---------- */
const LEAD_COLS = [
  { key: "rank", label: "Rk", cls: "rk", val: (r) => r.rank },
  { key: "name", label: "Player", cls: "l", val: (r) => norm(r.name), dir: 1 },
  { key: "gs", label: "GS", cls: "hide-sm", val: (r) => r.gs, dir: -1 },
  { key: "sgv", label: "SGV", val: (r) => net(r.sgv) * 1000 + r.sgv[0], dir: -1 },
  { key: "nd", label: "ND", cls: "hide-md", val: (r) => r.sgv[2], dir: -1 },
  { key: "dist", label: "W · ND · L", cls: "l hide-sm" },
  { key: "real", label: "Real", val: (r) => net(r.act) * 1000 + r.act[0], dir: -1 },
  { key: "swing", label: "Swing", cls: "hide-md", val: (r) => r.swing, dir: -1 },
  { key: "avg", label: "Avg SGV", val: (r) => r.avg, dir: 1 },
];
const playerLink = (r) => `<a href="#lookup" data-name="${esc(r.name)}">${esc(r.name)}</a><span class="tm">${esc(r.team)}</span>`;
function renderLeaders(d) {
  const col = LEAD_COLS.find((c) => c.key === sort.key);
  const rows = [...d.all].sort((a, b) => (col.val(a) > col.val(b) ? 1 : col.val(a) < col.val(b) ? -1 : a.rank - b.rank) * sort.dir);
  const shown = expanded ? rows : rows.slice(0, 10);
  const maxGs = Math.max(...d.all.map((r) => r.gs));
  const avgMetric = METRICS[0];
  const head = LEAD_COLS.map((c) => {
    const s = c.val ? ` class="sortable ${c.cls || ""}" data-key="${c.key}"` : ` class="${c.cls || ""}"`;
    const aria = c.key === sort.key ? ` aria-sort="${sort.dir === 1 ? "ascending" : "descending"}"` : "";
    return `<th scope="col"${s}${aria}>${c.label}</th>`;
  }).join("");
  const body = shown.map((r) => {
    const seg = (n, c, label) => n ? `<i style="width:${(n / maxGs) * 100}%;background:var(${c})" title="${n} SGV ${label}"></i>` : "";
    const p = percentile(d, avgMetric, r.avg);
    return `<tr><td class="rk">${r.rank}</td><td class="l">${playerLink(r)}</td><td class="hide-sm">${r.gs}</td>
      <td class="rec">${rec(r.sgv)}</td><td class="hide-md">${r.sgv[2]}</td>
      <td class="l hide-sm"><div class="dist">${seg(r.sgv[0], "--w", "W")}${seg(r.sgv[2], "--nd", "ND")}${seg(r.sgv[1], "--l", "L")}</div></td>
      <td>${rec(r.act)}</td><td class="hide-md"><span class="swing ${r.swing > 0 ? "pos" : r.swing < 0 ? "neg" : ""}">${signed(r.swing)}</span></td>
      <td><span class="pct" style="background:${pctColor(p)}" title="${p}th percentile">${dec2(r.avg)}</span></td></tr>`;
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
document.getElementById("leaders-more").addEventListener("click", () => { expanded = !expanded; renderLeaders(seasonData()); });

/* ---------- hard luck / fortunate ---------- */
function dumbbell(r, lo, hi, color, width) {
  const w = Math.max(60, width), h = 22, pad = 7, sx = (v) => pad + (v - lo) / (hi - lo) * (w - 2 * pad);
  const svg = el("svg", { viewBox: `0 0 ${w} ${h}`, role: "img", "aria-label": `${r.name}: real ${rec(r.act)}, SGV ${rec(r.sgv)}` });
  svg.append(el("line", { x1: sx(0), x2: sx(0), y1: 1, y2: h - 1, stroke: "var(--lg)", "stroke-width": 1, "stroke-dasharray": "2 2" }));
  const a = sx(net(r.act)), b = sx(net(r.sgv));
  svg.append(el("line", { x1: a, x2: b, y1: h / 2, y2: h / 2, stroke: color, "stroke-width": 2.5, opacity: 0.5 }));
  const ring = el("circle", { cx: a, cy: h / 2, r: 4.5, fill: "var(--panel)", stroke: "var(--ink-4)", "stroke-width": 2 });
  ring.append(el("title", {}, `Real ${rec(r.act)} (${signed(net(r.act))} net)`));
  const dot = el("circle", { cx: b, cy: h / 2, r: 5.5, fill: color, stroke: "rgba(0,0,0,.55)", "stroke-width": 1 });
  dot.append(el("title", {}, `SGV ${rec(r.sgv)} (${signed(net(r.sgv))} net)`));
  svg.append(ring, dot);
  return svg;
}
function renderSwing(id, rows, lo, hi, color) {
  const table = document.getElementById(id);
  table.innerHTML = `<thead><tr><th class="rk">Rk</th><th class="l">Player</th><th>Real</th><th>SGV</th><th>Swing</th>
    <th class="l viz hide-sm">Real → SGV</th></tr></thead><tbody>${
    rows.map((r, i) => `<tr><td class="rk">${i + 1}</td><td class="l">${playerLink(r)}</td><td>${rec(r.act)}</td>
      <td class="rec">${rec(r.sgv)}</td><td><span class="swing ${r.swing > 0 ? "pos" : "neg"}">${signed(r.swing)}</span></td>
      <td class="l viz hide-sm"></td></tr>`).join("") || `<tr><td colspan="6" class="l">No qualified starters yet.</td></tr>`}</tbody>`;
  table.querySelectorAll("td.viz").forEach((td, i) => {
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
  } else if (e.key === "Enter" && active >= 0) { e.preventDefault(); choose(matches[active]); }
  else if (e.key === "Escape") { matchList.hidden = true; }
});
matchList.addEventListener("mousedown", (e) => {
  const li = e.target.closest("li[data-i]");
  if (li) { e.preventDefault(); choose(matches[+li.dataset.i]); }
});
searchBox.addEventListener("blur", () => { matchList.hidden = true; });
document.addEventListener("click", (e) => {
  const a = e.target.closest("a[data-name]");
  if (!a) return;
  const p = seasonData().players.find((x) => x.n === a.dataset.name);
  if (!p) return;
  e.preventDefault();   // keep the #pitcher= link instead of jumping to #lookup
  choose(p);
  document.getElementById("lookup").scrollIntoView();
});

const BALL = `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="1.8"/>` +
  `<path d="M7 4.5c2 2.2 2 12.8 0 15M17 4.5c-2 2.2-2 12.8 0 15" fill="none" stroke="var(--w)" stroke-width="1.6"/></svg>`;
const ARM = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20l6-6 3 3 7-11" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;

function profileCard(p, d) {
  const seasons = DATA.map((x) => ({ season: x.season, p: x.players.find((y) => y.id === p.id) })).filter((x) => x.p);
  const row = (label, q, cls = "") => {
    const era = q.outs ? (27 * q.er / q.outs).toFixed(2) : "–";
    return `<tr class="${cls}"><td class="l">${label}</td><td>${q.gs}</td><td>${ipText(q.outs)}</td><td>${era}</td>
      <td>${rec(q.s)}</td><td>${rec(q.a)}</td><td class="hide-sm">${signed(net(q.s) - net(q.a))}</td><td>${dec2(q.avg)}</td></tr>`;
  };
  const rows = seasons.map((x) => row(x.season, { gs: x.p.g.length, outs: x.p.outs, er: x.p.er, s: x.p.s, a: x.p.a, avg: x.p.avg })).join("");
  const sum = (f) => seasons.reduce((t, x) => t + f(x.p), 0);
  const tot = { gs: sum((q) => q.g.length), outs: sum((q) => q.outs), er: sum((q) => q.er),
    s: [0, 1, 2].map((i) => sum((q) => q.s[i])), a: [0, 1, 2].map((i) => sum((q) => q.a[i])),
    avg: sum((q) => q.avg * q.g.length) / sum((q) => q.g.length) };
  const initials = p.n.split(" ").map((w) => w[0]).filter(Boolean).slice(0, 2).join("");
  const rank = p.rank ? `SGV rank #${p.rank} of ${d.qualified} qualified` : `Not qualified in ${d.season} (min. ${d.qualifier} GS)`;
  const ph = META.photos[p.id];
  const avatar = ph
    ? `<div class="avatar" data-initials="${esc(initials)}"><img src="${esc(ph[0])}" alt="${esc(p.n)}" loading="lazy" referrerpolicy="no-referrer"></div>`
    : `<div class="avatar" aria-hidden="true">${esc(initials)}</div>`;
  const credit = ph
    ? `<p class="credit">Photo: <a href="${esc(ph[1])}" target="_blank" rel="noopener">${esc(ph[2])}</a> · ${esc(ph[3])} · Wikimedia Commons</p>` : "";
  return `<div class="panel card"><div class="card-top">
      ${avatar}
      <h3 class="pname">${esc(p.n)}</h3>
      <p class="pline">SP | ${esc(p.t)} | ${d.season}</p>
      <p class="pline2">${rank}</p></div>
    <div class="scroll"><table class="t"><thead><tr><th class="l">Season</th><th>GS</th><th>IP</th><th>ERA</th><th>SGV</th>
      <th>Real</th><th class="hide-sm">Swing</th><th>Avg</th></tr></thead>
      <tbody>${rows}${seasons.length > 1 ? row("Total", tot, "total") : ""}</tbody></table></div>
    <p class="note">SGV and Real are W-L records; Avg is the mean SGV per start (lower is better).</p>${credit}</div>`;
}

function percentilePanel(p, d) {
  const block = (group, icon) => `<div class="phead">${icon}${group}</div>` + METRICS.filter((m) => m.group === group).map((m) => {
    const v = m.get(p), pc = percentile(d, m, v), c = pctColor(pc);
    return `<div class="prow"><div class="lab">${m.label}</div>
      <div class="pbar" role="img" aria-label="${m.label}: ${pc}th percentile">
        <div class="trk"></div><div class="fil" style="width:${pc}%;background:${c}"></div><div class="mid"></div>
        <div class="bdg" style="left:${pc}%;background:${c}">${pc}</div></div>
      <div class="val">${m.show(v)}</div></div>`;
  }).join("");
  return `<div class="panel"><h2 class="ptitle"><b>${d.season}</b> SGV Percentile Rankings</h2>
    ${p.q ? "" : `<p class="unq">Below the ${d.qualifier}-start minimum: compared with qualified starters.</p>`}
    <div class="plegend"><div></div><div class="scale"><span class="poor">Poor</span><span class="avg">Average</span><span class="great">Great</span></div><div></div></div>
    ${block("SGV", BALL)}${block("Pitching", ARM)}</div>`;
}

// 5-start rolling average SGV, better (negative) drawn upward, with league average and the W/L cut-offs.
function rollingChart(p, d, width) {
  const w = Math.max(300, width), h = 290, x0 = 44, x1 = w - 56, y0 = 12, y1 = 230;
  const roll = p.g.map((_, i) => { const s = p.g.slice(Math.max(0, i - 4), i + 1); return s.reduce((t, g) => t + g[5], 0) / s.length; });
  const lo = Math.min(-3, Math.floor(Math.min(...roll, d.wCut) * 2) / 2), hi = Math.max(2, Math.ceil(Math.max(...roll, d.lCut) * 2) / 2);
  const sy = (v) => y0 + (v - lo) / (hi - lo) * (y1 - y0);
  const sx = (i) => p.g.length === 1 ? (x0 + x1) / 2 : x0 + i / (p.g.length - 1) * (x1 - x0);
  const svg = el("svg", { viewBox: `0 0 ${w} ${h}`, role: "img", "aria-label": `${p.n}: 5-start rolling SGV, ${d.season}` });
  svg.append(el("line", { x1: x0, x2: x0, y1: y0, y2: y1, stroke: "var(--ink-2)" }));
  for (let v = Math.ceil(lo); v <= Math.floor(hi); v++) {
    svg.append(el("line", { x1: x0 - 4, x2: x0, y1: sy(v), y2: sy(v), stroke: "var(--ink-2)" }));
    svg.append(el("text", { x: x0 - 8, y: sy(v) + 4, class: "axis", "text-anchor": "end" }, v === 0 ? "0" : signed(v)));
    if (v % 1 === 0 && v !== 0) svg.append(el("line", { x1: x0, x2: x1, y1: sy(v), y2: sy(v), stroke: "var(--line)", "stroke-dasharray": "6 5" }));
  }
  const ref = (v, label, color, dash, sw) => {
    svg.append(el("line", { x1: x0, x2: x1, y1: sy(v), y2: sy(v), stroke: color, "stroke-dasharray": dash, "stroke-width": sw }));
    svg.append(el("text", { x: x1 + 6, y: sy(v) + 4, class: "lbl" }, label));
  };
  ref(d.wCut, "SGV W", "var(--w)", "3 4", 1);
  ref(d.lCut, "SGV L", "var(--l)", "3 4", 1);
  ref(d.lgAvg, "LG AVG", "var(--lg)", "7 4", 2);
  // line, coloured red where better than league average and grey-blue where worse
  for (let i = 1; i < roll.length; i++) {
    const better = (roll[i - 1] + roll[i]) / 2 < d.lgAvg;
    svg.append(el("line", { x1: sx(i - 1), x2: sx(i), y1: sy(roll[i - 1]), y2: sy(roll[i]),
      stroke: better ? "var(--roll)" : "var(--l)", "stroke-width": 2.5, "stroke-linecap": "round" }));
  }
  if (roll.length === 1) svg.append(el("circle", { cx: sx(0), cy: sy(roll[0]), r: 3, fill: "var(--roll)" }));
  // one square per start, coloured by SGV decision
  const band = (x1 - x0) / p.g.length, sq = Math.max(3, Math.min(12, band - 2));
  p.g.forEach((g, i) => {
    const [date, opp, ha, outs, er, sgv, dec, act] = g;
    const r = el("rect", { x: x0 + i * band + (band - sq) / 2, y: 252, width: sq, height: 12,
      fill: dec === "W" ? "var(--w)" : dec === "L" ? "var(--l)" : "var(--nd)" });
    r.append(el("title", {}, `${date} ${ha === "H" ? "vs" : "@"} ${opp}: ${ipText(outs)} IP, ${er} ER, SGV ${dec2(sgv)} (SGV ${dec}, real ${act})`));
    svg.append(r);
  });
  svg.append(el("text", { x: x0, y: 282, class: "lbl" }, "Start 1"));
  svg.append(el("text", { x: x1, y: 282, class: "lbl", "text-anchor": "end" }, `Start ${p.g.length}`));
  svg.append(el("text", { x: x1 + 6, y: 262, class: "lbl" }, "Decision"));
  return svg;
}

function renderLookup() {
  const d = seasonData(), box = document.getElementById("player");
  document.querySelector("#lookup-title b").textContent = current;
  const p = selected === null ? null : d.players.find((x) => x.id === selected);
  if (selected !== null && !p) {
    const other = DATA.filter((x) => x.season !== current && x.players.some((y) => y.id === selected));
    const name = DATA.flatMap((x) => x.players).find((y) => y.id === selected).n;
    box.innerHTML = `<div class="panel"><p class="empty">${esc(name)} made no starts in ${current}.` +
      other.map((x) => ` <button class="linkish" data-season="${x.season}">See ${x.season}</button>`).join("") + "</p></div>";
    box.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => renderSeason(+b.dataset.season)));
    return;
  }
  if (!p) { box.replaceChildren(); return; }   // nothing shown until a pitcher is searched
  const shown = p;
  box.innerHTML = `<div class="pgrid" style="margin-top:16px">
      ${profileCard(shown, d)}
      ${percentilePanel(shown, d)}
      <div class="panel roll"><h2 class="ptitle"><b>5-Start</b> Rolling SGV</h2>
        <div class="key"><span><i class="sq" style="background:var(--roll)"></i>better than league average</span><span><i class="sq" style="background:var(--l)"></i>worse</span></div>
        <div class="chart" id="roll-chart"></div>
        <p class="note">Lower SGV is better, so the axis runs from best at the top to worst at the bottom. Squares: each start's SGV decision; hover for the line.</p></div>
    </div>
    <div class="panel" style="margin-top:16px"><details class="log"><summary>${d.season} Game Log · ${esc(shown.n)} · ${shown.g.length} starts</summary>
      <div class="scroll"><table class="t"><thead><tr><th class="l">Date</th><th class="l">Opp</th><th>IP</th><th>ER</th><th>SGV</th>
        <th>SGV Dec</th><th>Real Dec</th><th class="hide-sm">Team</th></tr></thead><tbody>${
        shown.g.map(([date, opp, ha, outs, er, sgv, dec, act, res]) => `<tr><td class="l">${date}</td><td class="l">${ha === "H" ? "vs" : "@"} ${esc(opp)}</td>
        <td>${ipText(outs)}</td><td>${er}</td><td>${dec2(sgv)}</td><td><span class="dec dec-${dec}">${dec}</span></td><td>${act}</td>
        <td class="hide-sm">${res}</td></tr>`).join("")}</tbody></table></div></details></div>`;
  // A photo that fails to load falls back to the initials.
  box.querySelectorAll(".avatar img").forEach((img) => img.addEventListener("error", () => {
    const a = img.parentNode;
    a.textContent = a.dataset.initials;
    a.setAttribute("aria-hidden", "true");
    a.closest(".panel").querySelector(".credit")?.remove();
  }));
  const holder = document.getElementById("roll-chart");
  holder.append(rollingChart(shown, d, Math.round(holder.clientWidth)));
}

/* ---------- season ---------- */
function renderSeason(season) {
  current = season;
  const d = seasonData();
  document.querySelectorAll("#seasons button").forEach((b) => b.setAttribute("aria-selected", String(+b.dataset.season === season)));
  document.querySelectorAll(".ptitle b.yr").forEach((b) => { b.textContent = season; });
  document.getElementById("band").textContent = d.band;
  document.getElementById("qual").textContent = `${d.qualified} qualified starters, min. ${d.qualifier} GS · click a column to sort`;
  renderScoreboard(d);
  renderLeaders(d);
  const vals = [...d.hardLuck, ...d.fortunate].flatMap((r) => [net(r.act), net(r.sgv)]);
  const lo = Math.min(-5, Math.floor(Math.min(...vals, 0) / 5) * 5), hi = Math.max(5, Math.ceil(Math.max(...vals, 0) / 5) * 5);
  renderSwing("hard-luck-table", d.hardLuck, lo, hi, "var(--w)");
  renderSwing("fortunate-table", d.fortunate, lo, hi, "var(--l)");
  const blend = d.currentWeight < 1
    ? `Early season: league averages are ${Math.round(d.currentWeight * 100)}% ${season} and ${Math.round((1 - d.currentWeight) * 100)}% ${season - 1} until ${season} has enough games. ` : "";
  document.getElementById("foot").textContent = blend +
    `${season}: SGV W if SGV < ${dec2(d.wCut)}, SGV L if SGV > +${d.lCut.toFixed(2)}, SGV ND in between (team win probability ${d.band}). ` +
    `Thresholds are fixed for the season, calibrated on ${d.calibratedOn}. League bullpen RA9 ${d.ra9.toFixed(2)}, ${d.rpg.toFixed(2)} runs per team game.`;
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
let resizeTimer, lastW = innerWidth;
addEventListener("resize", () => {
  if (innerWidth === lastW) return;   // ignore mobile address-bar height changes
  lastW = innerWidth;
  clearTimeout(resizeTimer); resizeTimer = setTimeout(() => renderSeason(current), 150);
});
</script>
</body>
</html>
"""
