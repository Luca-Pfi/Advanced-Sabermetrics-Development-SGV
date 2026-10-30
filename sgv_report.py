"""
HTML leaderboards for SGV records (self-contained, no extra libraries).

Three boards per season, for qualified starters:
  * Best SGV Records      - ranked by SGV W minus SGV L
  * Hard-Luck Starters    - SGV record most BETTER than the real W-L record
  * Fortunate Starters    - SGV record most WORSE than the real W-L record

"Swing" = (SGV W - SGV L) - (Actual W - Actual L), in net wins.

Below the boards, a pitcher lookup searches every starter of the selected
season and shows the SGV season line, a per-start SGV chart and the game log.
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
    best = sorted(rows, key=lambda r: (-(r["sgv"][0] - r["sgv"][1]), r["avg"]))[:TOP_N]
    hard_luck = sorted([r for r in rows if r["swing"] > 0],
                       key=lambda r: (-r["swing"], r["avg"]))[:TOP_N]
    fortunate = sorted([r for r in rows if r["swing"] < 0],
                       key=lambda r: (r["swing"], -r["avg"]))[:TOP_N]
    return {"season": season, "qualifier": qualifier, "qualified": len(rows),
            "best": best, "hardLuck": hard_luck, "fortunate": fortunate}


def season_pitchers(df, season, qualifier):
    """Every starter of a season, compact, for the pitcher lookup."""
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
    # SGV rank among qualified starters, same order as the Best SGV Records board
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
        board.update({
            "wCut": round(t["sgv_w_below"], 2), "lCut": round(t["sgv_l_above"], 2),
            "band": f"{t['nd_band']:.0%} - {1 - t['nd_band']:.0%}",
            "calibratedOn": t["calibrated_on"],
            "currentWeight": league[s]["current_weight"],
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
<style>
:root {
  color-scheme: light;
  --surface-0: #f6f5f2; --surface-1: #fcfcfb; --border: #e4e2dc; --grid: #ebe9e4;
  --text-primary: #0b0b0b; --text-secondary: #52514e; --text-muted: #7a7974;
  --win: #2a78d6; --nd: #b4b2a9; --loss: #e34948; --actual: #7a7974;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --surface-0: #121211; --surface-1: #1a1a19; --border: #2e2e2c; --grid: #262624;
    --text-primary: #f0efec; --text-secondary: #c3c2b7; --text-muted: #8f8e88;
    --win: #3987e5; --nd: #55544f; --loss: #e66767; --actual: #8f8e88;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --surface-0: #121211; --surface-1: #1a1a19; --border: #2e2e2c; --grid: #262624;
  --text-primary: #f0efec; --text-secondary: #c3c2b7; --text-muted: #8f8e88;
  --win: #3987e5; --nd: #55544f; --loss: #e66767; --actual: #8f8e88;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--surface-0); color: var(--text-primary);
       font: 14px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 860px; margin: 0 auto; padding: 28px 16px 48px; }
h1 { font-size: 26px; margin: 0 0 2px; letter-spacing: -0.01em; }
#through { margin: 0 0 10px; }
.lede { color: var(--text-secondary); margin: 0 0 12px; max-width: 64ch; }
.formula { margin: 0 0 20px; padding: 10px 14px; background: var(--surface-1); border: 1px solid var(--border);
           border-radius: 8px; font: 13.5px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
           color: var(--text-primary); overflow-wrap: break-word; }
.controls { display: flex; gap: 8px; align-items: center; margin-bottom: 20px; flex-wrap: wrap; }
.seg { display: inline-flex; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.seg button { border: 0; background: var(--surface-1); color: var(--text-secondary);
              padding: 6px 14px; font: inherit; cursor: pointer; }
.seg button + button { border-left: 1px solid var(--border); }
.seg button[aria-pressed="true"] { background: var(--text-primary); color: var(--surface-1); }
.note { color: var(--text-muted); font-size: 12.5px; }
section.card { background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px;
               padding: 18px 18px 12px; margin-bottom: 18px; }
.card h2 { font-size: 17px; margin: 0; }
.card .sub { color: var(--text-secondary); margin: 2px 0 10px; font-size: 13px; }
.legend { display: flex; gap: 16px; flex-wrap: wrap; font-size: 12.5px; color: var(--text-secondary);
          margin-bottom: 6px; }
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.sw { width: 12px; height: 12px; border-radius: 3px; display: inline-block; }
.dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
svg { display: block; width: 100%; height: auto; overflow: visible; }
svg text { font-family: inherit; }
.name { fill: var(--text-primary); font-size: 13px; }
.team { fill: var(--text-muted); font-size: 11.5px; }
.val { fill: var(--text-secondary); font-size: 12px; font-variant-numeric: tabular-nums; }
.val strong, .strong { fill: var(--text-primary); font-weight: 600; }
.axis { fill: var(--text-muted); font-size: 11px; }
.row-hit { fill: transparent; }
.row:hover .row-hit { fill: var(--grid); }
details { margin-top: 8px; }
summary { cursor: pointer; color: var(--text-secondary); font-size: 12.5px; }
table { border-collapse: collapse; width: 100%; margin-top: 8px; font-size: 12.5px;
        font-variant-numeric: tabular-nums; }
th, td { text-align: right; padding: 4px 6px; border-bottom: 1px solid var(--grid); }
th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) { text-align: left; }
th { color: var(--text-secondary); font-weight: 600; }
.table-wrap { overflow-x: auto; }
#tip { position: fixed; pointer-events: none; z-index: 10; background: var(--surface-1);
       color: var(--text-primary); border: 1px solid var(--border); border-radius: 8px;
       padding: 8px 10px; font-size: 12.5px; box-shadow: 0 4px 16px rgba(0,0,0,.12);
       opacity: 0; transition: opacity .08s; max-width: 260px; }
#tip b { display: block; margin-bottom: 2px; }
#tip .k { color: var(--text-secondary); }
footer { color: var(--text-muted); font-size: 12px; margin-top: 8px; }
.search { position: relative; max-width: 420px; margin: 4px 0 6px; }
.search input { width: 100%; padding: 9px 12px; font: inherit; color: var(--text-primary);
                background: var(--surface-0); border: 1px solid var(--border); border-radius: 8px; }
.search input:focus { outline: 2px solid var(--win); outline-offset: 1px; }
.search ul { position: absolute; z-index: 5; left: 0; right: 0; top: calc(100% + 4px); margin: 0; padding: 4px;
             list-style: none; background: var(--surface-1); border: 1px solid var(--border);
             border-radius: 8px; box-shadow: 0 6px 20px rgba(0,0,0,.12); max-height: 280px; overflow-y: auto; }
.search li { padding: 6px 8px; border-radius: 6px; cursor: pointer; display: flex; justify-content: space-between;
             gap: 12px; }
.search li span { color: var(--text-muted); font-size: 12.5px; }
.search li[aria-selected="true"], .search li:hover { background: var(--grid); }
.player-head { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; margin: 14px 0 10px; }
.player-head h3 { margin: 0; font-size: 18px; }
.player-head span { color: var(--text-secondary); }
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(100px, 1fr)); gap: 8px; margin-bottom: 12px; }
.stat { border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; }
.stat .k { color: var(--text-secondary); font-size: 12px; }
.stat .v { font-size: 20px; font-weight: 600; font-variant-numeric: tabular-nums; }
.stat .v small { display: block; font-size: 12px; font-weight: 400; color: var(--text-secondary); }
.dec { display: inline-block; min-width: 26px; padding: 0 5px; border-radius: 4px; text-align: center;
       font-size: 11.5px; font-weight: 600; color: #fff; }
.dec-W { background: var(--win); } .dec-L { background: var(--loss); }
.dec-ND { background: var(--nd); color: var(--text-primary); }
.empty { color: var(--text-secondary); margin: 12px 0 4px; }
.linkish { border: 0; background: none; padding: 0; font: inherit; color: var(--win); cursor: pointer;
           text-decoration: underline; }
</style>
</head>
<body>
<main>
  <h1>SGV Leaderboards</h1>
  <p class="note" id="through"></p>
  <p class="lede">Starter Game Value credits each start as an SGV win, loss or no-decision based on the
  pitching alone. It assumes a league-average offense and bullpen and adjusts for the ballpark.
  A start is an SGV ND when it left the team a <span id="band"></span> chance to win.</p>
  <p class="formula" aria-label="SGV formula">SGV = (ER + Bullpen RA9 × (9 − IP) / 9) − (Runs per team game × Park factor)</p>
  <div class="controls">
    <div class="seg" id="seasons" role="group" aria-label="Season"></div>
    <span class="note" id="qual"></span>
  </div>
  <div id="boards"></div>
  <section class="card" id="lookup">
    <h2 id="lookup-title">Pitcher lookup</h2>
    <p class="sub">Search any starter to see their SGV record and every start of the selected season.</p>
    <div class="search">
      <input id="search" type="search" placeholder="Search a pitcher, e.g. Skenes" autocomplete="off"
             role="combobox" aria-expanded="false" aria-controls="matches" aria-autocomplete="list"
             aria-label="Search a pitcher">
      <ul id="matches" role="listbox" hidden></ul>
    </div>
    <div id="player"></div>
  </section>
  <footer id="foot"></footer>
</main>
<div id="tip" role="tooltip"></div>
<script>
const DATA = __DATA__;
const META = __META__;
const NS = "http://www.w3.org/2000/svg";
const ROW = 30, TOP = 8;
let W = 760, LABEL = 190, NARROW = false;   // set from the container width in render()
const tip = document.getElementById("tip");

function el(tag, attrs = {}, text) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (text !== undefined) n.textContent = text;
  return n;
}
const rec = (a) => `${a[0]}-${a[1]}`;
const recNd = (a) => `${a[0]}-${a[1]}-${a[2]}`;
const net = (a) => a[0] - a[1];
const signed = (n) => (n > 0 ? "+" : n < 0 ? "−" : "") + Math.abs(n);

function showTip(e, p) {
  tip.innerHTML = `<b>${p.name} <span class="k">${p.team}</span></b>
    <div><span class="k">Starts</span> ${p.gs}</div>
    <div><span class="k">SGV W-L-ND</span> ${recNd(p.sgv)}</div>
    <div><span class="k">Real W-L-ND</span> ${recNd(p.act)}</div>
    <div><span class="k">Avg SGV</span> ${p.avg.toFixed(2)}</div>
    <div><span class="k">Swing</span> ${signed(p.swing)} net wins</div>`;
  tip.style.opacity = 1;
  const x = Math.min(e.clientX + 14, innerWidth - tip.offsetWidth - 8);
  const y = Math.min(e.clientY + 14, innerHeight - tip.offsetHeight - 8);
  tip.style.left = x + "px"; tip.style.top = y + "px";
}
function hideTip() { tip.style.opacity = 0; }

function nameLabel(svg, p, i, y) {
  const parts = p.name.split(" ");
  const name = NARROW && parts.length > 1 ? `${parts[0][0]}. ${parts.slice(1).join(" ")}` : p.name;
  svg.append(el("text", { x: 0, y: y + 4, class: "name" }, `${i + 1}. ${name}`));
  if (!NARROW) {
    svg.append(el("text", { x: LABEL - 6, y: y + 4, class: "team", "text-anchor": "end" }, p.team));
  }
}
// One <g> per pitcher: hovering anywhere on the row (label, bar, dots) shows the tooltip.
function rowGroup(svg, p, y) {
  const g = el("g", { class: "row" });
  g.append(el("rect", { x: 0, y: y - ROW / 2, width: W, height: ROW, class: "row-hit", rx: 4 }));
  g.addEventListener("mousemove", (e) => showTip(e, p));
  g.addEventListener("mouseleave", hideTip);
  svg.append(g);
  return g;
}

// Stacked W | ND | L bar, length = games started.
function recordChart(rows) {
  const maxGs = Math.max(...rows.map((r) => r.gs));
  const plotW = W - LABEL - (NARROW ? 44 : 96);
  const svg = el("svg", { viewBox: `0 0 ${W} ${TOP + rows.length * ROW}`, role: "img",
                         "aria-label": "Best SGV records, stacked SGV wins, no-decisions and losses" });
  rows.forEach((p, i) => {
    const y = TOP + i * ROW + ROW / 2;
    const g = rowGroup(svg, p, y);
    nameLabel(g, p, i, y);
    let x = LABEL;
    const segs = [[p.sgv[0], "var(--win)"], [p.sgv[2], "var(--nd)"], [p.sgv[1], "var(--loss)"]];
    segs.forEach(([n, color]) => {
      if (!n) return;
      const w = (n / maxGs) * plotW;
      g.append(el("rect", { x, y: y - 8, width: Math.max(w - 2, 1), height: 16, fill: color, rx: 3 }));
      x += w;
    });
    const t = el("text", { x: x + 6, y: y + 4, class: "val" });
    t.append(el("tspan", { class: "strong" }, rec(p.sgv)));
    if (!NARROW) t.append(el("tspan", {}, ` · ${p.sgv[2]} ND`));
    g.append(t);
  });
  return svg;
}

// Dumbbell: real net wins (hollow) -> SGV net wins (filled), shared scale per season.
function swingChart(rows, lo, hi, color) {
  const plotL = LABEL + 8, plotR = W - (NARROW ? 40 : 150);
  const sx = (v) => plotL + ((v - lo) / (hi - lo)) * (plotR - plotL);
  const h = TOP + rows.length * ROW + 22;
  const svg = el("svg", { viewBox: `0 0 ${W} ${h}`, role: "img",
                         "aria-label": "Real net wins versus SGV net wins per pitcher" });
  const step = NARROW ? 10 : 5;
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) {
    svg.append(el("line", { x1: sx(v), x2: sx(v), y1: TOP - 4, y2: h - 18,
                            stroke: v === 0 ? "var(--text-muted)" : "var(--grid)",
                            "stroke-width": 1 }));
    svg.append(el("text", { x: sx(v), y: h - 4, class: "axis", "text-anchor": "middle" }, signed(v)));
  }
  rows.forEach((p, i) => {
    const y = TOP + i * ROW + ROW / 2;
    const g = rowGroup(svg, p, y);
    nameLabel(g, p, i, y);
    const a = sx(net(p.act)), b = sx(net(p.sgv));
    g.append(el("line", { x1: a, x2: b, y1: y, y2: y, stroke: color, "stroke-width": 2,
                            "stroke-linecap": "round", opacity: 0.55 }));
    g.append(el("circle", { cx: a, cy: y, r: 5, fill: "var(--surface-1)",
                              stroke: "var(--actual)", "stroke-width": 2 }));
    g.append(el("circle", { cx: b, cy: y, r: 5.5, fill: color,
                              stroke: "var(--surface-1)", "stroke-width": 2 }));
    const t = el("text", { x: plotR + 14, y: y + 4, class: "val" });
    if (NARROW) {
      t.append(el("tspan", { class: "strong" }, signed(p.swing)));
    } else {
      t.append(el("tspan", {}, `${rec(p.act)} → `));
      t.append(el("tspan", { class: "strong" }, rec(p.sgv)));
      t.append(el("tspan", {}, `  ${signed(p.swing)}`));
    }
    g.append(t);
  });
  return svg;
}

function table(rows) {
  const wrap = document.createElement("div");
  wrap.className = "table-wrap";
  wrap.innerHTML = `<table><thead><tr><th>#</th><th>Pitcher</th><th>Team</th><th>GS</th>
    <th>SGV W-L-ND</th><th>Real W-L-ND</th><th>Avg SGV</th><th>Swing</th></tr></thead><tbody>${
    rows.map((p, i) => `<tr><td>${i + 1}</td><td>${p.name}</td><td>${p.team}</td><td>${p.gs}</td>
      <td>${recNd(p.sgv)}</td><td>${recNd(p.act)}</td><td>${p.avg.toFixed(2)}</td>
      <td>${signed(p.swing)}</td></tr>`).join("")}</tbody></table>`;
  return wrap;
}

function card(title, sub, legendHtml, chart, rows) {
  const s = document.createElement("section");
  s.className = "card";
  s.innerHTML = `<h2>${title}</h2><p class="sub">${sub}</p><div class="legend">${legendHtml}</div>`;
  if (rows.length) {
    s.append(chart);
  } else {
    s.insertAdjacentHTML("beforeend", `<p class="sub">No qualified starters yet.</p>`);
  }
  const d = document.createElement("details");
  d.innerHTML = "<summary>Show as table</summary>";
  d.append(table(rows));
  s.append(d);
  return s;
}

function render(season) {
  const d = DATA.find((x) => x.season === season);
  current = season;
  document.getElementById("band").textContent = d.band;
  const blend = d.currentWeight < 1
    ? `Early season: league averages are ${Math.round(d.currentWeight * 100)}% ${season} and ` +
      `${Math.round((1 - d.currentWeight) * 100)}% ${season - 1} until ${season} has enough games. `
    : "";
  document.getElementById("foot").textContent = blend +
    `${season} thresholds (fixed for the season, calibrated on ${d.calibratedOn}): ` +
    `SGV W if SGV < ${d.wCut}, SGV L if SGV > ${d.lCut}. ` +
    "Data: MLB Stats API; park factors: FanGraphs.";
  W = Math.max(300, Math.round(document.getElementById("boards").clientWidth - 38));
  NARROW = W < 560;
  LABEL = NARROW ? 118 : 190;
  document.querySelectorAll("#seasons button").forEach((b) =>
    b.setAttribute("aria-pressed", String(+b.dataset.season === season)));
  document.getElementById("qual").textContent =
    `${d.qualified} qualified starters (min. ${d.qualifier} GS)`;
  const swings = [...d.hardLuck, ...d.fortunate].flatMap((p) => [net(p.act), net(p.sgv)]);
  const lo = Math.min(-5, Math.floor(Math.min(...swings) / 5) * 5);
  const hi = Math.max(5, Math.ceil(Math.max(...swings) / 5) * 5);
  const recLegend = `<span><i class="sw" style="background:var(--win)"></i>SGV W</span>
    <span><i class="sw" style="background:var(--nd)"></i>SGV ND</span>
    <span><i class="sw" style="background:var(--loss)"></i>SGV L</span>`;
  const swLegend = (c) => `<span><i class="dot" style="border:2px solid var(--actual)"></i>Real record</span>
    <span><i class="dot" style="background:${c}"></i>SGV record</span>
    <span>Net wins (W−L) · swing = SGV net − real net</span>`;
  const boards = document.getElementById("boards");
  boards.replaceChildren(
    card(`Best SGV Records — ${season}`,
         "Most SGV wins over SGV losses. Bar length is games started.",
         recLegend, recordChart(d.best), d.best),
    card(`Hard-Luck Starters — ${season}`,
         "Pitched better than their real record shows: run support or the bullpen let them down.",
         swLegend("var(--win)"), swingChart(d.hardLuck, lo, hi, "var(--win)"), d.hardLuck),
    card(`Fortunate Starters — ${season}`,
         "Real record is better than their pitching earned: the offense or bullpen bailed them out.",
         swLegend("var(--loss)"), swingChart(d.fortunate, lo, hi, "var(--loss)"), d.fortunate),
  );
  renderLookup();
  try { localStorage.setItem("sgv-season", season); } catch (e) {}
}

const seg = document.getElementById("seasons");
DATA.forEach((d) => {
  const b = document.createElement("button");
  b.textContent = d.season; b.dataset.season = d.season;
  b.addEventListener("click", () => render(d.season));
  seg.append(b);
});
document.getElementById("through").textContent = "Updated through games of " +
  new Date(META.through + "T12:00:00").toLocaleDateString("en-US",
    { month: "long", day: "numeric", year: "numeric" });
let current, start = DATA[DATA.length - 1].season;
let selected = null;   // pitcher id shown in the lookup
const norm = (t) => t.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
const ipText = (outs) => `${Math.floor(outs / 3)}.${outs % 3}`;
const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const seasonData = () => DATA.find((x) => x.season === current);
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

// SGV of every start; negative (good) drawn upward, dashed lines at the season's W and L cut-offs.
function startChart(p, d) {
  const w = W, h = 146, x0 = 34, y0 = 10, plotH = 130;
  const vals = p.g.map((g) => g[5]);
  const top = Math.min(-3, Math.floor(Math.min(...vals, d.wCut))), bot = Math.max(3, Math.ceil(Math.max(...vals, d.lCut)));
  const sy = (v) => y0 + (v - top) / (bot - top) * plotH;
  const band = (w - x0 - 4) / p.g.length, bw = Math.max(2, Math.min(18, band - 2));
  const svg = el("svg", { viewBox: `0 0 ${w} ${h}`, role: "img", "aria-label": `SGV of each ${p.n} start in ${d.season}` });
  for (let v = top; v <= bot; v++) {
    if (v % 2) continue;
    svg.append(el("line", { x1: x0, x2: w, y1: sy(v), y2: sy(v), stroke: v === 0 ? "var(--text-muted)" : "var(--grid)" }));
    svg.append(el("text", { x: x0 - 6, y: sy(v) + 4, class: "axis", "text-anchor": "end" }, v === 0 ? "0" : signed(v)));
  }
  [[d.wCut, "W"], [d.lCut, "L"]].forEach(([v, k]) => {
    svg.append(el("line", { x1: x0, x2: w, y1: sy(v), y2: sy(v), stroke: k === "W" ? "var(--win)" : "var(--loss)",
                            "stroke-dasharray": "4 4", opacity: 0.8 }));
  });
  p.g.forEach((g, i) => {
    const [date, opp, ha, outs, er, sgv, dec, act] = g;
    const x = x0 + i * band + (band - bw) / 2, ya = sy(0), yb = sy(sgv);
    const r = el("rect", { x, y: Math.min(ya, yb), width: bw, height: Math.max(1, Math.abs(yb - ya)), rx: 2,
      fill: dec === "W" ? "var(--win)" : dec === "L" ? "var(--loss)" : "var(--nd)" });
    r.append(el("title", {}, `${date} ${ha === "H" ? "vs" : "@"} ${opp}: ${ipText(outs)} IP, ${er} ER, ` +
      `SGV ${sgv.toFixed(2)} (SGV ${dec}, real ${act})`));
    svg.append(r);
  });
  return svg;
}

function renderLookup() {
  const d = seasonData(), box = document.getElementById("player");
  document.getElementById("lookup-title").textContent = `Pitcher lookup — ${current}`;
  if (selected === null) { box.replaceChildren(); return; }
  const p = d.players.find((x) => x.id === selected);
  if (!p) {
    const other = DATA.filter((x) => x.season !== current && x.players.some((y) => y.id === selected));
    const name = DATA.flatMap((x) => x.players).find((y) => y.id === selected).n;
    box.innerHTML = `<p class="empty">${esc(name)} made no starts in ${current}.` +
      other.map((x) => ` <button class="linkish" data-season="${x.season}">See ${x.season}</button>`).join("") + "</p>";
    box.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => render(+b.dataset.season)));
    return;
  }
  const net = p.s[0] - p.s[1], swing = net - (p.a[0] - p.a[1]);
  const era = p.outs ? (27 * p.er / p.outs).toFixed(2) : "–";
  const stat = (k, v, small = "") => `<div class="stat"><div class="k">${k}</div><div class="v">${v}` +
    (small ? ` <small>${small}</small>` : "") + "</div></div>";
  box.innerHTML = `<div class="player-head"><h3>${esc(p.n)}</h3><span>${esc(p.t)} · ${current}</span></div>
    <div class="stats">
      ${stat("SGV record", `${p.s[0]}-${p.s[1]}`, `${p.s[2]} ND`)}
      ${stat("Real record", `${p.a[0]}-${p.a[1]}`, `${p.a[2]} ND`)}
      ${stat("Swing", signed(swing), "net wins")}
      ${stat("Avg SGV", p.avg.toFixed(2))}
      ${stat("GS · IP", `${p.g.length}`, `${ipText(p.outs)} IP`)}
      ${stat("ERA", era, `${p.er} ER`)}
      ${stat("SGV rank", p.rank ? `#${p.rank}` : "–", p.rank ? `of ${d.qualified}` : `not qualified (${d.qualifier} GS)`)}
    </div>`;
  box.append(startChart(p, d));
  box.insertAdjacentHTML("beforeend", `<p class="note">SGV of each start, in order. Bars above 0 were ` +
    `better than average; dashed lines are the SGV W (${d.wCut}) and SGV L (${d.lCut}) cut-offs. ` +
    `Hover a bar for the line.</p>`);
  const det = document.createElement("details");
  det.innerHTML = `<summary>Game log (${p.g.length} starts)</summary><div class="table-wrap"><table><thead><tr>
    <th>Date</th><th>Opp</th><th>IP</th><th>ER</th><th>SGV</th><th>SGV dec</th><th>Real dec</th><th>Team</th>
    </tr></thead><tbody>${p.g.map(([date, opp, ha, outs, er, sgv, dec, act, res]) => `<tr><td>${date}</td>
    <td>${ha === "H" ? "vs" : "@"} ${esc(opp)}</td><td>${ipText(outs)}</td><td>${er}</td><td>${sgv.toFixed(2)}</td>
    <td><span class="dec dec-${dec}">${dec}</span></td><td>${act}</td><td>${res}</td></tr>`).join("")}
    </tbody></table></div>`;
  box.append(det);
}
let resizeTimer;
addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => render(current), 120);
});
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
render(start);
</script>
</body>
</html>
"""
