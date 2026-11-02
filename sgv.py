"""
Starter Game Value (SGV) records.

For every regular-season start, SGV credits the starting pitcher with an
SGV Win, SGV Loss or SGV No-Decision, independent of the real game result:

    SGV = (ER + LgBullpenRA9 * (9 - IP) / 9) - (LgRunsPerTeamGame * ParkFactor)

The starter is charged with earned runs only; the bullpen term uses the
league bullpen RA9 (all runs, earned or not, per 9 IP). League bullpen RA9 and
runs per team per game are computed from that season's own games. Early in a
season they are blended with the previous season's values: the current season
weighs team_games / 60 (100% from about late May). Park factors are read from
park_factors.csv (FanGraphs); known ballparks carry over to a new season.

No-decision zone: a logistic curve P(team wins | SGV) is fitted, and a start
is an SGV ND when that win probability lies inside the ND band (default
40%-60%, i.e. too close to call):

    P(win) >  60%  -> SGV W   (gave the team a realistic chance to win)
    P(win) <  40%  -> SGV L
    otherwise      -> SGV ND

Each season's thresholds are calibrated once, on all earlier seasons, and
saved in nd_thresholds.csv, so they stay fixed for the whole season. Delete a
season's row there to recalibrate it.

Data comes from the MLB Stats API (statsapi.mlb.com, free, no key).
Box scores of finished games are cached in ./cache, so re-running during a
season only downloads the new games ("live" mode).

Usage:
    python sgv.py                         # 2025 and 2026 seasons
    python sgv.py --seasons 2025 2026 2027  # include earlier seasons for blending/calibration
    python sgv.py --watch 60              # re-run every 60 minutes

Outputs: sgv_records.xlsx (records, every start, model) and sgv_report.html
(leaderboards: Best SGV Records, Hard-Luck Starters, Fortunate Starters).
"""

import argparse
import csv
import json
import sys
import time
import webbrowser
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import requests

import photos
from sgv_report import write_report

API = "https://statsapi.mlb.com/api/v1"
HERE = Path(__file__).resolve().parent
CACHE_DIR = HERE / "cache"
PARK_FACTORS_FILE = HERE / "park_factors.csv"
OUTPUT_FILE = HERE / "sgv_records.xlsx"
REPORT_FILE = HERE / "sgv_report.html"
THRESHOLDS_FILE = HERE / "nd_thresholds.csv"

ND_BAND = 0.40          # SGV ND when the team's win probability is between 40% and 60%
BLEND_GAMES = 60        # league averages are 100% current season after 60 team games
DEFAULT_SEASONS = [2025, 2026]
SKIPPED_STATES = ("Postponed", "Cancelled", "Suspended")


# --------------------------------------------------------------------------
# Data access
# --------------------------------------------------------------------------

session = requests.Session()


def get_json(path, params=None, retries=4):
    for attempt in range(retries):
        try:
            r = session.get(f"{API}/{path}", params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** (attempt + 1))


def fetch_team_abbreviations(season):
    data = get_json("teams", {"sportId": 1, "season": season})
    return {t["id"]: t["abbreviation"] for t in data["teams"]}


def fetch_final_games(season):
    """All finished regular-season games of a season, one entry per gamePk."""
    data = get_json("schedule", {"sportId": 1, "season": season, "gameType": "R"})
    games = {}
    for day in data.get("dates", []):
        for g in day["games"]:
            status = g["status"]
            if status["abstractGameState"] != "Final":
                continue
            if any(s in status["detailedState"] for s in SKIPPED_STATES):
                continue
            # A suspended game appears again on its resumption date; keep the last one.
            games[g["gamePk"]] = {
                "gamePk": g["gamePk"],
                "date": g.get("officialDate", day["date"]),
                "venue": g["venue"]["name"],
                "home_id": g["teams"]["home"]["team"]["id"],
                "away_id": g["teams"]["away"]["team"]["id"],
                "home_score": g["teams"]["home"].get("score"),
                "away_score": g["teams"]["away"].get("score"),
            }
    return sorted(games.values(), key=lambda g: (g["date"], g["gamePk"]))


PITCHING_FIELDS = ("outs", "inningsPitched", "earnedRuns", "runs", "gamesStarted", "wins", "losses")


def slim_boxscore(box):
    """Keep only what SGV uses (pitcher lines and runs): ~2 KB instead of ~180 KB per game."""
    teams = {}
    for side in ("home", "away"):
        t = box["teams"][side]
        players = {}
        for pid in t["pitchers"]:
            player = t["players"][f"ID{pid}"]
            pitching = player.get("stats", {}).get("pitching", {})
            players[f"ID{pid}"] = {
                "person": {"id": pid, "fullName": player["person"]["fullName"]},
                "stats": {"pitching": {k: pitching[k] for k in PITCHING_FIELDS if k in pitching}},
            }
        teams[side] = {
            "team": {"id": t["team"]["id"]},
            "teamStats": {"batting": {"runs": t["teamStats"]["batting"]["runs"]}},
            "pitchers": t["pitchers"],
            "players": players,
        }
    return {"teams": teams}


def fetch_boxscore(game, refresh=False):
    """Box score for a finished game, read from the cache when possible."""
    path = CACHE_DIR / f"{game['gamePk']}.json"
    if path.exists() and not refresh:
        box = json.loads(path.read_text())
        if "info" not in box:          # already slim
            return box
    else:
        box = get_json(f"game/{game['gamePk']}/boxscore")
    box = slim_boxscore(box)
    path.write_text(json.dumps(box))
    return box


def fetch_boxscores(games, refresh_since):
    CACHE_DIR.mkdir(exist_ok=True)
    # Recent games are re-downloaded so official scoring changes (ER) are picked up.
    jobs = [(g, g["date"] >= refresh_since) for g in games]
    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(lambda job: fetch_boxscore(*job), jobs))


# --------------------------------------------------------------------------
# SGV calculation
# --------------------------------------------------------------------------

def outs_of(pitching):
    """Outs recorded; falls back to converting baseball IP notation (4.2 = 4 2/3)."""
    if "outs" in pitching:
        return int(pitching["outs"])
    whole, _, thirds = str(pitching.get("inningsPitched", "0")).partition(".")
    return int(whole) * 3 + int(thirds or 0)


def side_lines(box_side):
    """(starter_line, reliever_lines) for one team in a box score."""
    lines = []
    for pid in box_side["pitchers"]:
        player = box_side["players"][f"ID{pid}"]
        p = player.get("stats", {}).get("pitching", {})
        lines.append({
            "id": pid,
            "name": player["person"]["fullName"],
            "outs": outs_of(p),
            "er": int(p.get("earnedRuns", 0)),
            "r": int(p.get("runs", 0)),
            "gs": int(p.get("gamesStarted", 0)),
            "w": int(p.get("wins", 0)),
            "l": int(p.get("losses", 0)),
        })
    if not lines:
        return None, []
    starter_idx = next((i for i, x in enumerate(lines) if x["gs"] == 1), 0)
    return lines[starter_idx], lines[:starter_idx] + lines[starter_idx + 1:]


def extract_starts(games, boxes, abbrevs):
    """One row per start, plus season totals for the league averages."""
    starts = []
    runs = team_games = relief_runs = relief_outs = 0
    for game, box in zip(games, boxes):
        for side, opp_side in (("home", "away"), ("away", "home")):
            team_id = game[f"{side}_id"]
            score = game[f"{side}_score"]
            if score is None:
                score = box["teams"][side]["teamStats"]["batting"]["runs"]
            runs += score
            team_games += 1

            starter, relievers = side_lines(box["teams"][side])
            if starter is None:
                continue
            relief_runs += sum(r["r"] for r in relievers)
            relief_outs += sum(r["outs"] for r in relievers)

            opp_score = game[f"{opp_side}_score"]
            starts.append({
                "date": game["date"],
                "gamePk": game["gamePk"],
                "pitcher_id": starter["id"],
                "pitcher": starter["name"],
                "team": abbrevs.get(team_id, str(team_id)),
                "opponent": abbrevs.get(game[f"{opp_side}_id"], ""),
                "home_away": "H" if side == "home" else "A",
                "venue": game["venue"],
                "home_team": abbrevs.get(game["home_id"], ""),
                "IP": starter["outs"] / 3,
                "ER": starter["er"],
                "team_result": "W" if score > (opp_score or 0) else "L",
                "actual_dec": "W" if starter["w"] else "L" if starter["l"] else "ND",
            })
    league = {
        "games": len(games),
        "runs_per_team_game": runs / team_games if team_games else float("nan"),
        "bullpen_ra9": 27 * relief_runs / relief_outs if relief_outs else float("nan"),
    }
    return starts, league


def sgv_value(er, ip, bullpen_ra9, runs_per_game, park_factor):
    remaining = max(0.0, 9 - ip)   # a start of 9+ IP leaves nothing for the bullpen
    return (er + bullpen_ra9 * remaining / 9) - runs_per_game * park_factor


def fit_win_curve(sgv, team_won, iterations=25):
    """Logistic fit P(win) = 1 / (1 + exp(-(a + b * SGV))), by Newton's method.

    A tiny ridge penalty keeps the fit finite on a handful of starts; with a
    full season of data its effect is negligible.
    """
    x = np.asarray(sgv, dtype=float)
    y = np.asarray(team_won, dtype=float)
    X = np.column_stack([np.ones_like(x), x])
    ridge = 0.1 * np.eye(2)
    coef = np.zeros(2)
    for _ in range(iterations):
        p = 1 / (1 + np.exp(-X @ coef))
        hessian = X.T @ (X * (p * (1 - p))[:, None]) + ridge
        coef += np.linalg.solve(hessian, X.T @ (y - p) - ridge @ coef)
    return coef


def win_probability(sgv, coef):
    return 1 / (1 + np.exp(-(coef[0] + coef[1] * sgv)))


def nd_thresholds(coef, band=ND_BAND):
    """SGV values where the win probability equals 1-band (W cut) and band (L cut)."""
    sgv_at = lambda p: (np.log(p / (1 - p)) - coef[0]) / coef[1]
    return sgv_at(1 - band), sgv_at(band)


def sgv_decision(sgv, w_cut, l_cut):
    if sgv < w_cut:
        return "W"
    if sgv > l_cut:
        return "L"
    return "ND"


def blend_league_averages(season_to_date, previous):
    """Early in a season, mix the season-to-date league averages with last season's.

    The current season's weight grows linearly with team games played and reaches
    100% at BLEND_GAMES (about late May); a finished season is never blended.
    """
    team_games = 2 * season_to_date["games"] / 30
    weight = min(1.0, team_games / BLEND_GAMES) if previous else 1.0
    league = {"games": season_to_date["games"], "team_games": round(team_games, 1),
              "current_weight": round(weight, 3)}
    for key in ("runs_per_team_game", "bullpen_ra9"):
        league[f"{key}_season_to_date"] = season_to_date[key]
        league[key] = (weight * season_to_date[key]
                       + (1 - weight) * (previous[key] if previous else 0))
    return league


# --------------------------------------------------------------------------
# ND thresholds, frozen per season in nd_thresholds.csv
# --------------------------------------------------------------------------

THRESHOLD_COLUMNS = ["season", "nd_band", "sgv_w_below", "sgv_l_above",
                     "curve_a", "curve_b", "calibrated_on", "starts"]


def load_thresholds():
    if not THRESHOLDS_FILE.exists():
        return {}
    with THRESHOLDS_FILE.open(newline="", encoding="utf-8-sig") as f:
        rows = {}
        for r in csv.DictReader(f):
            rows[int(r["season"])] = {
                **r, **{k: float(r[k]) for k in
                        ("nd_band", "sgv_w_below", "sgv_l_above", "curve_a", "curve_b")}}
        return rows


def save_thresholds(thresholds):
    with THRESHOLDS_FILE.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=THRESHOLD_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for season in sorted(thresholds):
            w.writerow({**thresholds[season], "season": season})


def season_thresholds(all_starts, band):
    """ND thresholds for every season scored.

    A season's thresholds are calibrated once - on all EARLIER seasons loaded
    (the earliest season, having none, uses every season loaded) - then saved
    to nd_thresholds.csv and kept for the whole season, so records don't shift
    from day to day. Delete a season's row to recalibrate it.
    """
    thresholds = load_thresholds()
    seasons = sorted({s["season"] for s in all_starts})
    changed = False
    for season in seasons:
        stored = thresholds.get(season)
        if stored:
            if abs(stored["nd_band"] - band) > 1e-9:
                print(f"[{season}] using the saved ND band {stored['nd_band']:.0%} "
                      f"(delete its row in {THRESHOLDS_FILE.name} to recalibrate)")
            continue
        basis = [s for s in all_starts if s["season"] < season] or all_starts
        basis_seasons = sorted({s["season"] for s in basis})
        coef = fit_win_curve([s["SGV"] for s in basis],
                             [s["team_result"] == "W" for s in basis])
        w_cut, l_cut = nd_thresholds(coef, band)
        thresholds[season] = {
            "nd_band": band, "sgv_w_below": round(w_cut, 3), "sgv_l_above": round(l_cut, 3),
            "curve_a": round(coef[0], 5), "curve_b": round(coef[1], 5),
            "calibrated_on": "-".join(map(str, dict.fromkeys([basis_seasons[0], basis_seasons[-1]]))),
            "starts": len(basis),
        }
        changed = True
        print(f"[{season}] ND thresholds calibrated on {thresholds[season]['calibrated_on']}: "
              f"SGV W below {w_cut:.2f}, SGV L above {l_cut:.2f} (saved)")
    if changed:
        save_thresholds(thresholds)
    return {season: thresholds[season] for season in seasons}


# --------------------------------------------------------------------------
# Park factors (filled in by hand from FanGraphs)
# --------------------------------------------------------------------------

def load_park_factors():
    pf = {}
    if PARK_FACTORS_FILE.exists():
        with PARK_FACTORS_FILE.open(newline="", encoding="utf-8-sig") as f:
            # Excel in a French locale saves CSV with ";" and decimal commas.
            delimiter = ";" if ";" in f.readline() else ","
            f.seek(0)
            for row in csv.DictReader(f, delimiter=delimiter):
                value = (row.get("park_factor") or "").strip().replace(",", ".")
                pf[(int(row["season"]), row["venue"])] = {
                    "home_team": row.get("home_team", ""),
                    "games": row.get("games", ""),
                    "park_factor": float(value) if value else None,
                    "note": row.get("note") or "",
                }
    return pf


def carried_value(pf, season, venue):
    """Most recent earlier season's park factor for the same ballpark, if any."""
    earlier = [(s, e["park_factor"]) for (s, v), e in pf.items()
               if v == venue and s < season and e["park_factor"] is not None]
    return max(earlier) if earlier else (None, None)


def update_park_factor_file(pf, season, starts):
    """Add any new (season, venue) rows to park_factors.csv.

    A ballpark already used in an earlier season gets that season's value,
    flagged in the note column so it can be checked against FanGraphs; only a
    brand-new ballpark is left blank for the user to fill in.
    """
    usage = defaultdict(lambda: [set(), set()])
    for s in starts:
        usage[s["venue"]][0].add(s["home_team"])
        usage[s["venue"]][1].add(s["gamePk"])
    carried = []
    for venue, (teams, game_ids) in usage.items():
        entry = pf.setdefault((season, venue), {"park_factor": None, "note": ""})
        entry["home_team"] = "/".join(sorted(teams))
        entry["games"] = len(game_ids)
        if entry["park_factor"] is None:
            from_season, value = carried_value(pf, season, venue)
            if value is not None:
                entry["park_factor"] = value
                entry["note"] = f"carried from {from_season} - check FanGraphs"
                carried.append(venue)
    if carried:
        print(f"[{season}] park factors carried from the previous season for "
              f"{len(carried)} ballparks (update them from FanGraphs when available)")

    with PARK_FACTORS_FILE.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["season", "venue", "home_team", "games", "park_factor", "note"])
        for (s, venue), e in sorted(pf.items()):
            value = "" if e["park_factor"] is None else e["park_factor"]
            w.writerow([s, venue, e.get("home_team", ""), e.get("games", ""), value,
                        e.get("note", "")])


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def run(seasons, band, refresh_days, open_report=False):
    refresh_since = (pd.Timestamp.today() - pd.Timedelta(days=refresh_days)).strftime("%Y-%m-%d")
    pf = load_park_factors()
    all_starts, league_rows, missing = [], [], []
    league_by_season = {}

    for season in sorted(seasons):
        print(f"[{season}] fetching schedule ...")
        games = fetch_final_games(season)
        if not games:
            print(f"[{season}] no finished games yet")
            continue
        abbrevs = fetch_team_abbreviations(season)
        print(f"[{season}] {len(games)} finished games, loading box scores ...")
        boxes = fetch_boxscores(games, refresh_since)
        starts, season_to_date = extract_starts(games, boxes, abbrevs)
        update_park_factor_file(pf, season, starts)
        league = blend_league_averages(season_to_date, league_by_season.get(season - 1))
        league_by_season[season] = league
        league_rows.append({"season": season, **league})
        blend = (f" ({league['current_weight']:.0%} {season}, "
                 f"{1 - league['current_weight']:.0%} {season - 1})"
                 if league["current_weight"] < 1 else "")
        print(f"[{season}] bullpen RA9 {league['bullpen_ra9']:.2f}, "
              f"runs/team/game {league['runs_per_team_game']:.2f}{blend}")

        for s in starts:
            factor = pf[(season, s["venue"])]["park_factor"]
            if factor is None:
                missing.append((season, s["venue"]))
                continue
            s["season"] = season
            s["park_factor"] = factor
            s["SGV"] = sgv_value(s["ER"], s["IP"], league["bullpen_ra9"],
                                 league["runs_per_team_game"], factor)
            all_starts.append(s)

    if missing:
        print(f"\nMissing park factors in {PARK_FACTORS_FILE.name} "
              f"(fill them in from FanGraphs, then run again):")
        for season, venue in sorted(set(missing)):
            print(f"  {season}  {venue}")
        return False

    thresholds = season_thresholds(all_starts, band)
    for s in all_starts:
        t = thresholds[s["season"]]
        s["win_prob"] = win_probability(s["SGV"], (t["curve_a"], t["curve_b"]))
        s["SGV_dec"] = sgv_decision(s["SGV"], t["sgv_w_below"], t["sgv_l_above"])

    # Latest name and team of every starter, for the photo lookup and its review files
    players = {s["pitcher_id"]: (s["pitcher"], s["team"]) for s in sorted(all_starts, key=lambda s: s["date"])}
    photo_table = photos.refresh(players)
    write_output(all_starts, league_rows, seasons, thresholds)
    write_report(pd.DataFrame(all_starts), league_rows, thresholds, REPORT_FILE, photo_table)
    print(f"\nWrote {OUTPUT_FILE}\nWrote {REPORT_FILE}")
    if open_report:
        webbrowser.open(REPORT_FILE.as_uri())
    return True


def counts(df, col):
    return tuple(int((df[col] == x).sum()) for x in ("W", "L", "ND"))


def write_output(starts, league_rows, seasons, thresholds):
    df = pd.DataFrame(starts)
    seasons = [s for s in seasons if (df["season"] == s).any()]
    rows = []
    for pid, p in df.groupby("pitcher_id"):
        row = {"Pitcher": p["pitcher"].iloc[-1]}
        for season in seasons:
            s = p[p["season"] == season]
            w, l, nd = counts(s, "SGV_dec")
            aw, al, and_ = counts(s, "actual_dec")
            # GS = SGV W + SGV L + SGV ND, and likewise for the actual decisions.
            row.update({
                f"{season} Team": "/".join(dict.fromkeys(s["team"])),
                f"{season} GS": len(s),
                f"{season} SGV W": w, f"{season} SGV L": l, f"{season} SGV ND": nd,
                f"{season} SGV W-L": f"{w}-{l}" if len(s) else "",
                f"{season} Avg SGV": round(s["SGV"].mean(), 2) if len(s) else None,
                f"{season} Actual W": aw, f"{season} Actual L": al, f"{season} Actual ND": and_,
                f"{season} Actual W-L": f"{aw}-{al}" if len(s) else "",
            })
        rows.append(row)
    sort_season = seasons[-1]
    summary = pd.DataFrame(rows).sort_values(
        [f"{sort_season} SGV W", f"{sort_season} SGV L"], ascending=[False, True])

    detail_cols = ["season", "date", "pitcher", "team", "opponent", "home_away", "venue",
                   "park_factor", "IP", "ER", "SGV", "win_prob", "SGV_dec", "actual_dec",
                   "team_result"]
    detail = df[detail_cols].sort_values(["season", "date", "pitcher"])
    detail["IP"] = detail["IP"].round(2)
    detail["SGV"] = detail["SGV"].round(2)
    detail["win_prob"] = detail["win_prob"].round(3)

    model_rows = []
    for lg in league_rows:
        season = lg["season"]
        s = df[df["season"] == season]
        t = thresholds[season]
        model_rows.append({
            "Season": season,
            "Games": lg["games"],
            "Team games": lg["team_games"],
            "Weight of this season": lg["current_weight"],
            "Bullpen RA9 (season to date)": lg["bullpen_ra9_season_to_date"],
            "Bullpen RA9 (used)": lg["bullpen_ra9"],
            "Runs/team/game (season to date)": lg["runs_per_team_game_season_to_date"],
            "Runs/team/game (used)": lg["runs_per_team_game"],
            "ND band": f"{t['nd_band']:.0%} - {1 - t['nd_band']:.0%}",
            "SGV W if SGV below": t["sgv_w_below"],
            "SGV L if SGV above": t["sgv_l_above"],
            "Thresholds calibrated on": t["calibrated_on"],
            "Starts": len(s),
            **{f"SGV {d}": int((s["SGV_dec"] == d).sum()) for d in ("W", "L", "ND")},
        })
    model = pd.DataFrame(model_rows).round(3)

    with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl") as xl:
        summary.to_excel(xl, sheet_name="SGV Records", index=False)
        detail.to_excel(xl, sheet_name="Starts", index=False)
        model.to_excel(xl, sheet_name="Model", index=False)
        for ws in xl.sheets.values():
            ws.freeze_panes = "B2"
            ws.auto_filter.ref = ws.dimensions
            for col in ws.columns:
                width = max(len(str(c.value or "")) for c in col)
                ws.column_dimensions[col[0].column_letter].width = min(width + 2, 34)


def main():
    ap = argparse.ArgumentParser(description="Starter Game Value (SGV) records")
    ap.add_argument("--seasons", type=int, nargs="+", default=DEFAULT_SEASONS,
                    help="seasons to score (default: 2025 2026)")
    ap.add_argument("--nd-band", type=float, default=ND_BAND,
                    help="SGV ND when team win probability is between this and 1 minus this "
                         "(default 0.40 = 40%%-60%%); applies to seasons not yet in "
                         "nd_thresholds.csv")
    ap.add_argument("--refresh-days", type=int, default=3,
                    help="re-download box scores from the last N days (scoring changes)")
    ap.add_argument("--no-open", action="store_true",
                    help="do not open the HTML report in the browser when done")
    ap.add_argument("--watch", type=int, metavar="MINUTES",
                    help="keep running, updating every N minutes")
    args = ap.parse_args()

    open_report = not args.no_open
    while True:
        ok = run(args.seasons, args.nd_band, args.refresh_days, open_report)
        open_report = False   # in --watch mode, open the browser only once
        if not args.watch:
            sys.exit(0 if ok else 1)   # non-zero so a scheduled run shows as failed
        print(f"Next update in {args.watch} min (Ctrl+C to stop)")
        time.sleep(args.watch * 60)


if __name__ == "__main__":
    main()
