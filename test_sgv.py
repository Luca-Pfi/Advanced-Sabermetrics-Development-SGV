"""Offline test of sgv.py with a fake MLB Stats API."""
import shutil, sys, tempfile
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sgv

tmp = Path(tempfile.mkdtemp())
sgv.CACHE_DIR = tmp / "cache"
sgv.PARK_FACTORS_FILE = tmp / "park_factors.csv"
sgv.OUTPUT_FILE = tmp / "out.xlsx"
sgv.REPORT_FILE = tmp / "report.html"

TEAMS = {1: "COL", 2: "SDP", 3: "LAD", 4: "CHC"}
VENUE = {1: "Coors Field", 2: "Petco Park", 3: "Dodger Stadium", 4: "Wrigley Field"}

def pitcher(pid, name, ip, er, gs=0, w=0, l=0):
    whole, thirds = divmod(ip, 3)
    return pid, {"person": {"id": pid, "fullName": name},
                 "stats": {"pitching": {"inningsPitched": f"{whole}.{thirds}",
                                        "earnedRuns": er, "runs": er + (pid % 2), "gamesStarted": gs,
                                        "wins": w, "losses": l}}}

def side(team, runs, lines):
    return {"team": {"id": team}, "teamStats": {"batting": {"runs": runs}},
            "pitchers": [p[0] for p in lines],
            "players": {f"ID{p[0]}": p[1] for p in lines}}

# gamePk -> (date, home, away, hs, as, venue, status, home lines, away lines) ; IP given in outs
G = {
 2025: [
  (1, "2025-04-01", 1, 2, 5, 3, None, "Final",
   [pitcher(10, "Rocky Starter", 21, 4, gs=1, w=1), pitcher(11, "Col Rp", 6, 1)],
   [pitcher(20, "Pad Ace", 18, 2, gs=1, l=1), pitcher(21, "Pad Rp", 6, 3)]),
  (2, "2025-04-02", 3, 4, 2, 1, "Tokyo Dome", "Final",
   [pitcher(31, "Opener Guy", 3, 0), pitcher(30, "Dodger Bulk", 24, 1, gs=1, w=1)],  # gs flag not first
   [pitcher(40, "Cub Ace", 28, 0, gs=1), pitcher(41, "Cub Rp", 0, 2, l=1)]),  # 9.1 IP
  (3, "2025-04-03", 2, 1, 0, 0, None, "Postponed", [], []),
  (4, "2025-04-04", 2, 1, 1, 0, None, "Suspended: Rain", [], []),
  (4, "2025-04-05", 2, 1, 4, 2, None, "Final",
   [pitcher(20, "Pad Ace", 20, 1, gs=1, w=1)],
   [pitcher(10, "Rocky Starter", 15, 6, gs=1, l=1), pitcher(11, "Col Rp", 12, 0)]),
 ],
 2026: [
  (5, "2026-04-01", 4, 3, 3, 2, None, "Final",
   [pitcher(40, "Cub Ace", 18, 2, gs=1, w=1)],
   [pitcher(30, "Dodger Bulk", 17, 3, gs=1, l=1), pitcher(32, "LAD Rp", 7, 0)]),
 ],
}

def fake_get_json(path, params=None, retries=4):
    if path == "teams":
        return {"teams": [{"id": i, "abbreviation": a} for i, a in TEAMS.items()]}
    if path == "schedule":
        games = []
        for pk, d, h, a, hs, as_, venue, st, *_ in G[params["season"]]:
            games.append({"gamePk": pk, "officialDate": d,
                          "status": {"abstractGameState": "Final", "detailedState": st},
                          "venue": {"name": venue or VENUE[h]},
                          "teams": {"home": {"team": {"id": h}, "score": hs},
                                    "away": {"team": {"id": a}, "score": as_}}})
        return {"dates": [{"date": g["officialDate"], "games": [g]} for g in games]}
    pk = int(path.split("/")[1])
    for season in G.values():
        for g in season:
            if g[0] == pk and g[7] == "Final":
                return {"teams": {"home": side(g[2], g[4], g[8]), "away": side(g[3], g[5], g[9])}}
    raise KeyError(path)

sgv.get_json = fake_get_json

# 1st run: no park factors -> template created, returns False
assert sgv.run([2025, 2026], 0.40, 3) is False
print(sgv.PARK_FACTORS_FILE.read_text())

pf = {"Coors Field": "1.10", "Petco Park": "0,95", "Dodger Stadium": "0.95",
      "Wrigley Field": "1.00", "Tokyo Dome": "1.00"}
lines = sgv.PARK_FACTORS_FILE.read_text().splitlines()
out = [lines[0].replace(",", ";")] + [(l + pf[l.split(",")[1]].replace(".", ",")).replace(",", ";", 4) for l in lines[1:]]
sgv.PARK_FACTORS_FILE.write_text("\n".join(out) + "\n")

assert sgv.run([2025, 2026], 0.40, 3) is True
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
for sh in ("Model", "Starts", "SGV Records"):
    print(f"--- {sh}"); print(pd.read_excel(sgv.OUTPUT_FILE, sheet_name=sh))

# hand check: 2025 league: runs (5+3+2+1+4+2)/6 = 2.8333
# relief runs (ER + 1 for odd ids): 11->2, 21->4, 31->1, 41->3, 11->1 = 11, outs 27 -> RA9 11.0
st = pd.read_excel(sgv.OUTPUT_FILE, sheet_name="Starts")
r = st[(st.pitcher == "Rocky Starter") & (st.date == "2025-04-01")].iloc[0]
exp = (4 + 11.0 * (9 - 7) / 9) - (17 / 6) * 1.10
assert abs(r.SGV - round(exp, 2)) < 0.01, (r.SGV, exp)
cub = st[(st.pitcher == "Cub Ace") & (st.season == 2025)].iloc[0]
assert abs(cub.SGV - round(0 - 17 / 6, 2)) < 0.01  # 9.1 IP -> no bullpen term
assert set(st[st.season == 2025].pitcher) == {"Rocky Starter", "Pad Ace", "Dodger Bulk", "Cub Ace"}
assert len(st) == 8
assert sorted(st.park_factor.unique()) == [0.95, 1.0, 1.1], st.park_factor.unique()
# every summary row: GS = SGV W + SGV L + SGV ND
sm = pd.read_excel(sgv.OUTPUT_FILE, sheet_name="SGV Records")
for y in (2025, 2026):
    assert (sm[f"{y} GS"] == sm[f"{y} SGV W"] + sm[f"{y} SGV L"] + sm[f"{y} SGV ND"]).all()
    assert (sm[f"{y} GS"] == sm[f"{y} Actual W"] + sm[f"{y} Actual L"] + sm[f"{y} Actual ND"]).all()

# win-curve fit recovers known coefficients and places the ND cut-offs correctly
import numpy as np
rng = np.random.default_rng(0)
x = rng.normal(0, 2, 200_000)
won = rng.random(x.size) < 1 / (1 + np.exp(-(-0.1 - 0.5 * x)))
coef = sgv.fit_win_curve(x, won)
assert np.allclose(coef, [-0.1, -0.5], atol=0.02), coef
w_cut, l_cut = sgv.nd_thresholds(coef, 0.40)
assert abs(sgv.win_probability(w_cut, coef) - 0.60) < 1e-9 and w_cut < l_cut
assert sgv.sgv_decision(w_cut - 0.01, w_cut, l_cut) == "W"
assert sgv.sgv_decision(l_cut + 0.01, w_cut, l_cut) == "L"
assert sgv.sgv_decision((w_cut + l_cut) / 2, w_cut, l_cut) == "ND"
assert "SGV Leaderboards" in sgv.REPORT_FILE.read_text()
shutil.rmtree(tmp)
print("ALL CHECKS PASSED")
