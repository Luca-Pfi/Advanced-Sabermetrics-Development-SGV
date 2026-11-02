"""
SGV for the minor leagues: Triple-A, Double-A, High-A and Single-A.

Same record as the MLB version (ER + bullpen runs for the innings left, against an average
offense in that park), with three differences that matter in the minors:

* League averages are per league (e.g. Pacific Coast vs International League), not per level,
  because run environments differ a lot between leagues of the same level.
* 7-inning doubleheaders: the bullpen covers (scheduled innings - IP) and the run baseline is
  scaled to the scheduled length, so a 7-inning game isn't judged as if it were 9.
* Park factors are computed from the games themselves, since FanGraphs doesn't publish
  minor-league ones: runs per 9 innings at the home park versus the home team's road games,
  regressed halfway to 1.00. They are written to milb_park_factors.csv; a value typed in the
  `override` column wins.

ND thresholds are calibrated per level, the same way as for MLB: once per season, on that
level's earlier seasons, then kept fixed (milb_nd_thresholds.csv).
"""

import csv
from collections import defaultdict
from pathlib import Path

import pandas as pd

import sgv
from sgv_report import write_report

HERE = Path(__file__).resolve().parent
LEVELS = [(11, "AAA", "Triple-A"), (12, "AA", "Double-A"), (13, "A+", "High-A"), (14, "A", "Single-A")]
REPORT_FILE = HERE / "sgv_milb.html"
OUTPUT_FILE = HERE / "sgv_milb_records.xlsx"
THRESHOLDS_FILE = HERE / "milb_nd_thresholds.csv"
PARK_FILE = HERE / "milb_park_factors.csv"
PF_REGRESS = 0.5        # computed park factors are pulled halfway to 1.00 (one season is a small sample)
PF_MIN_GAMES = 20       # parks with fewer home games (neutral sites) get 1.00


# --------------------------------------------------------------------------
# One level and season: starts, league averages, park factors
# --------------------------------------------------------------------------

def level_season(games, boxes, teams):
    """Starts of one level and season, with per-league averages and computed park factors."""
    lg = defaultdict(lambda: {"runs": 0.0, "units": 0.0, "relief_runs": 0, "relief_outs": 0, "games": 0, "teams": set()})
    home = defaultdict(lambda: [0.0, 0.0])      # team -> [runs in its home games, 9-inning units]
    road = defaultdict(lambda: [0.0, 0.0])      # team -> [runs in its road games, 9-inning units]
    venue_team, venue_games = {}, defaultdict(int)
    starts = []
    for game, box in zip(games, boxes):
        league = teams.get(game["home_id"], ("", ""))[1]
        units = game.get("innings", 9) / 9
        total = 0
        lg[league]["games"] += 1
        lg[league]["teams"].update([game["home_id"], game["away_id"]])
        for side, opp_side in (("home", "away"), ("away", "home")):
            score = game[f"{side}_score"]
            if score is None:
                score = box["teams"][side]["teamStats"]["batting"]["runs"]
            total += score
            lg[league]["runs"] += score
            lg[league]["units"] += units
            starter, relievers = sgv.side_lines(box["teams"][side])
            if starter is None:
                continue
            lg[league]["relief_runs"] += sum(r["r"] for r in relievers)
            lg[league]["relief_outs"] += sum(r["outs"] for r in relievers)
            opp_score = game[f"{opp_side}_score"]
            if opp_score is None:
                opp_score = box["teams"][opp_side]["teamStats"]["batting"]["runs"]
            starts.append({
                "date": game["date"], "gamePk": game["gamePk"], "pitcher_id": starter["id"],
                "pitcher": starter["name"], "team": teams.get(game[f"{side}_id"], (str(game[f"{side}_id"]), ""))[0],
                "opponent": teams.get(game[f"{opp_side}_id"], ("", ""))[0],
                "home_away": "H" if side == "home" else "A", "venue": game["venue"], "league": league,
                "innings": game.get("innings", 9), "home_id": game["home_id"],
                "IP": starter["outs"] / 3, "ER": starter["er"],
                "team_result": "W" if score > opp_score else "L",
                "actual_dec": "W" if starter["w"] else "L" if starter["l"] else "ND",
            })
        home[game["home_id"]][0] += total
        home[game["home_id"]][1] += units
        road[game["away_id"]][0] += total
        road[game["away_id"]][1] += units
        venue_games[(game["venue"], game["home_id"])] += 1
        venue_team.setdefault(game["venue"], game["home_id"])

    leagues = {}
    for name, v in lg.items():
        leagues[name] = {"games": v["games"], "teams": len(v["teams"]),
                         "runs_per_team_game": v["runs"] / v["units"] if v["units"] else float("nan"),
                         "bullpen_ra9": 27 * v["relief_runs"] / v["relief_outs"] if v["relief_outs"] else float("nan")}

    parks = {}
    for (venue, team), n in venue_games.items():
        h, r = home[team], road[team]
        if n < PF_MIN_GAMES or not h[1] or not r[1] or not r[0]:
            raw = 1.0
        else:
            raw = (h[0] / h[1]) / (r[0] / r[1])
        parks[(venue, team)] = {"games": n, "raw": raw, "pf": 1 + PF_REGRESS * (raw - 1)}
    return starts, leagues, parks


def blend(current, previous):
    """Early in a season, mix a league's averages with its previous season (same rule as MLB)."""
    team_games = 2 * current["games"] / max(1, current["teams"])
    weight = min(1.0, team_games / sgv.BLEND_GAMES) if previous else 1.0
    out = dict(current, team_games=round(team_games, 1), current_weight=round(weight, 3))
    for key in ("runs_per_team_game", "bullpen_ra9"):
        out[f"{key}_season_to_date"] = current[key]
        out[key] = weight * current[key] + (1 - weight) * (previous[key] if previous else 0)
    return out


def sgv_milb(er, ip, innings, bullpen_ra9, runs_per_9, park_factor):
    """SGV scaled to the scheduled length of the game (7 or 9 innings)."""
    return (er + bullpen_ra9 * max(0.0, innings - ip) / 9) - runs_per_9 * innings / 9 * park_factor


# --------------------------------------------------------------------------
# Park factor overrides and ND thresholds, per level
# --------------------------------------------------------------------------

def load_overrides():
    out = {}
    for r in sgv_read_csv(PARK_FILE):
        v = (r.get("override") or "").strip().replace(",", ".")
        if v:
            try:
                out[(r["level"], int(r["season"]), r["venue"])] = float(v)
            except ValueError:
                pass
    return out


def sgv_read_csv(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        delimiter = ";" if ";" in f.readline() else ","
        f.seek(0)
        return list(csv.DictReader(f, delimiter=delimiter))


def save_parks(rows):
    with PARK_FILE.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["level", "season", "venue", "home_team", "league", "games",
                                          "computed", "override"])
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r["level"], r["season"], r["venue"])))


def level_thresholds(starts, band):
    """{(level, season): thresholds}; calibrated once per level and season, then kept (like MLB)."""
    saved = {}
    for r in sgv_read_csv(THRESHOLDS_FILE):
        saved[(r["level"], int(r["season"]))] = {**r, **{k: float(r[k]) for k in
                                                 ("nd_band", "sgv_w_below", "sgv_l_above", "curve_a", "curve_b")}}
    out, changed = {}, False
    for level in sorted({s["level"] for s in starts}):
        lvl = [s for s in starts if s["level"] == level]
        for season in sorted({s["season"] for s in lvl}):
            if (level, season) in saved:
                out[(level, season)] = saved[(level, season)]
                continue
            basis = [s for s in lvl if s["season"] < season] or lvl
            seasons = sorted({s["season"] for s in basis})
            coef = sgv.fit_win_curve([s["SGV"] for s in basis], [s["team_result"] == "W" for s in basis])
            w_cut, l_cut = sgv.nd_thresholds(coef, band)
            out[(level, season)] = saved[(level, season)] = {
                "level": level, "season": season, "nd_band": band, "sgv_w_below": round(w_cut, 3),
                "sgv_l_above": round(l_cut, 3), "curve_a": round(coef[0], 5), "curve_b": round(coef[1], 5),
                "calibrated_on": "-".join(map(str, dict.fromkeys([seasons[0], seasons[-1]]))),
                "starts": len(basis)}
            changed = True
            print(f"[MiLB {level} {season}] ND thresholds: SGV W below {w_cut:.2f}, SGV L above {l_cut:.2f}")
    if changed:
        with THRESHOLDS_FILE.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["level", "season", "nd_band", "sgv_w_below", "sgv_l_above",
                                              "curve_a", "curve_b", "calibrated_on", "starts"], extrasaction="ignore")
            w.writeheader()
            w.writerows(saved[k] for k in sorted(saved))
    return out


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def run(seasons, band, refresh_since, photos=None):
    overrides = load_overrides()
    all_starts, league_rows, park_rows = [], [], []
    for sport_id, code, name in LEVELS:
        previous = {}
        for season in sorted(seasons):
            games = sgv.fetch_final_games(season, sport_id)
            if not games:
                continue
            teams = sgv.fetch_teams(season, sport_id)
            print(f"[MiLB {code} {season}] {len(games)} finished games, loading box scores ...")
            boxes = sgv.fetch_boxscores(games, refresh_since)
            starts, leagues, parks = level_season(games, boxes, teams)
            for (venue, team), p in parks.items():
                park_rows.append({"level": code, "season": season, "venue": venue,
                                  "home_team": teams.get(team, ("", ""))[0], "league": teams.get(team, ("", ""))[1],
                                  "games": p["games"], "computed": round(p["pf"], 3),
                                  "override": overrides.get((code, season, venue), "")})
            used = {}
            for lname, cur in leagues.items():
                used[lname] = blend(cur, previous.get(lname))
                league_rows.append({"level": code, "season": season, "league": lname, **used[lname]})
            previous = used
            pf_of = {(v, t): overrides.get((code, season, v), p["pf"]) for (v, t), p in parks.items()}
            for s in starts:
                L = used[s["league"]]
                s.update(level=code, season=season, park_factor=round(pf_of.get((s["venue"], s["home_id"]), 1.0), 3))
                s["SGV"] = sgv_milb(s["ER"], s["IP"], s["innings"], L["bullpen_ra9"], L["runs_per_team_game"],
                                    s["park_factor"])
            all_starts.extend(starts)
            avg = sum(L["runs_per_team_game"] for L in used.values()) / max(1, len(used))
            print(f"[MiLB {code} {season}] {len(starts)} starts, {len(used)} leagues, "
                  f"{avg:.2f} runs per team per 9 innings on average")
    if not all_starts:
        print("MiLB: no finished games")
        return False
    save_parks(park_rows)

    thresholds = level_thresholds(all_starts, band)
    for s in all_starts:
        t = thresholds[(s["level"], s["season"])]
        s["win_prob"] = sgv.win_probability(s["SGV"], (t["curve_a"], t["curve_b"]))
        s["SGV_dec"] = sgv.sgv_decision(s["SGV"], t["sgv_w_below"], t["sgv_l_above"])

    df = pd.DataFrame(all_starts)
    write_records(df)
    write_report(df, league_rows, thresholds, REPORT_FILE, photos, levels=[(c, n) for _, c, n in LEVELS])
    print(f"Wrote {OUTPUT_FILE}\nWrote {REPORT_FILE}")
    return True


def write_records(df):
    cols = ["level", "league", "season", "date", "pitcher", "team", "opponent", "home_away", "venue", "innings",
            "park_factor", "IP", "ER", "SGV", "win_prob", "SGV_dec", "actual_dec", "team_result"]
    starts = df[cols].sort_values(["level", "season", "date", "pitcher"]).copy()
    starts["IP"], starts["SGV"], starts["win_prob"] = starts["IP"].round(2), starts["SGV"].round(2), starts["win_prob"].round(3)
    rec = (df.groupby(["level", "season", "pitcher_id"])
             .agg(Pitcher=("pitcher", "last"), Team=("team", lambda t: "/".join(dict.fromkeys(t))), GS=("SGV", "size"),
                  **{f"SGV {d}": ("SGV_dec", lambda x, d=d: int((x == d).sum())) for d in ("W", "L", "ND")},
                  **{f"Real {d}": ("actual_dec", lambda x, d=d: int((x == d).sum())) for d in ("W", "L", "ND")},
                  **{"Avg SGV": ("SGV", lambda x: round(x.mean(), 2))})
             .reset_index().drop(columns="pitcher_id")
             .sort_values(["level", "season", "SGV W"], ascending=[True, True, False]))
    with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl") as xl:
        rec.to_excel(xl, sheet_name="SGV Records", index=False)
        starts.to_excel(xl, sheet_name="Starts", index=False)
        for ws in xl.sheets.values():
            ws.freeze_panes = "B2"
