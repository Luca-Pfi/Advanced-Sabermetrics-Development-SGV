"""Offline test of sgv.py with a fake MLB Stats API."""
import csv, shutil, sys, tempfile
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sgv

tmp = Path(tempfile.mkdtemp())
sgv.CACHE_DIR = tmp / "cache"
sgv.PARK_FACTORS_FILE = tmp / "park_factors.csv"
sgv.OUTPUT_FILE = tmp / "out.xlsx"
sgv.REPORT_FILE = tmp / "report.html"
sgv.THRESHOLDS_FILE = tmp / "nd_thresholds.csv"

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

# Photos, offline: Wikimedia has pitcher 10; Openverse has a candidate for pitcher 20 (Pad Ace).
import photos as ph
for attr, fname in (("PHOTOS_FILE", "player_photos.json"), ("REVIEW_FILE", "photo_review.csv"),
                    ("REVIEW_PAGE", "photo_review.html"), ("CROPS_FILE", "photo_crops.csv"),
                    ("SHEETS_DIR", "photo_check"), ("IMAGE_CACHE", "photo_cache")):
    setattr(ph, attr, tmp / fname)
ph.time.sleep = lambda s: None
wiki_calls = []
def fake_wiki_post(url, data):
    wiki_calls.append("sparql")
    assert "wdt:P3541" in data["query"]
    return {"results": {"bindings": [{"id": {"value": "10"},
            "image": {"value": "http://commons.wikimedia.org/wiki/Special:FilePath/Rocky%20Starter%202024.jpg"}}]}}
def fake_wiki_get(url, params, timeout=60):
    if url == ph.OPENVERSE_API:
        wiki_calls.append("openverse")
        if params["q"] != "Pad Ace":
            return {"results": []}
        return {"results": [
            {"title": "Pad Ace pitching in San Diego", "tags": [], "creator": "Bo",
             "url": "https://live.staticflickr.com/65535/123_abc_b.jpg", "license": "by", "license_version": "2.0",
             "foreign_landing_url": "https://www.flickr.com/photos/bo/123"},
            {"title": "Ballpark at night", "tags": [{"name": "baseball"}], "creator": "Cy",
             "url": "https://live.staticflickr.com/65535/456_def_b.jpg", "license": "by-sa", "license_version": "2.0",
             "foreign_landing_url": "https://www.flickr.com/photos/cy/456"}]}
    wiki_calls.append("commons")
    assert params["titles"] == "File:Rocky Starter 2024.jpg" and params["iiurlwidth"] == ph.THUMB_WIDTH
    return {"query": {"normalized": [{"from": "File:Rocky Starter 2024.jpg", "to": "File:Rocky Starter 2024.jpg"}],
            "pages": {"1": {"title": "File:Rocky Starter 2024.jpg", "imageinfo": [{
                "thumburl": "https://upload.wikimedia.org/thumb/rocky.jpg/500px-rocky.jpg",
                "url": "https://upload.wikimedia.org/rocky.jpg",
                "descriptionurl": "https://commons.wikimedia.org/wiki/File:Rocky_Starter_2024.jpg",
                "extmetadata": {"Artist": {"value": '<a href="//commons.wikimedia.org/wiki/User:Ann">Ann &amp; Co</a>'},
                                "LicenseShortName": {"value": "CC BY-SA 4.0"}}}]}}}}
def fake_download(url):   # every test photo: 200 x 300 grey JPEG
    import cv2, numpy as np
    return cv2.imencode(".jpg", np.full((300, 200, 3), 128, np.uint8))[1].tobytes()
ph._wiki_post, ph._wiki_get, ph._download = fake_wiki_post, fake_wiki_get, fake_download
ph.detect_face = lambda img: (80, 40, 120, 90)   # a 40 x 50 face near the top of every test photo

# 1st run: no park factors -> template created, returns False
assert sgv.run([2025, 2026], 0.40, 3) is False
print(sgv.PARK_FACTORS_FILE.read_text())

pf = {"Coors Field": "1.10", "Petco Park": "0,95", "Dodger Stadium": "0.95",
      "Wrigley Field": "1.00", "Tokyo Dome": "1.00"}
# save as a French-locale Excel would: ";" separators and decimal commas
import csv
rows = list(csv.DictReader(sgv.PARK_FACTORS_FILE.open()))
with sgv.PARK_FACTORS_FILE.open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=rows[0].keys(), delimiter=";")
    w.writeheader()
    for r in rows:
        r["park_factor"] = pf[r["venue"]].replace(".", ",")
        w.writerow(r)

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
report = sgv.REPORT_FILE.read_text()
assert "SGV Leaderboards" in report and 'id="lookup"' in report
# the lookup carries every starter of each season, qualified or not, with one entry per start
import json, re
data = json.loads(re.search(r"const DATA = (.*);\n", report).group(1))
lookup = {d["season"]: {p["n"]: p for p in d["players"]} for d in data}
assert set(lookup[2025]) == {"Rocky Starter", "Pad Ace", "Dodger Bulk", "Cub Ace"}
assert len(lookup[2025]["Rocky Starter"]["g"]) == 2 and lookup[2025]["Rocky Starter"]["outs"] == 36
# slim cache: trimming a box score keeps everything SGV needs
full = fake_get_json("game/1/boxscore")
full["info"] = ["lots", "of", "unused", "data"]
full["teams"]["home"]["players"]["ID10"]["stats"]["pitching"]["strikeOuts"] = 9
full["teams"]["home"]["players"]["ID10"]["stats"]["batting"] = {"hits": 1}
slim = sgv.slim_boxscore(full)
assert "info" not in slim
assert slim["teams"]["home"]["players"]["ID10"]["stats"] == {"pitching": {
    "inningsPitched": "7.0", "earnedRuns": 4, "runs": 4, "gamesStarted": 1, "wins": 1, "losses": 0}}
assert sgv.side_lines(slim["teams"]["home"]) == sgv.side_lines(full["teams"]["home"])

# park factors carry forward to a new season for known ballparks only
pf = sgv.load_park_factors()
new_season = [{"venue": "Coors Field", "home_team": "COL", "gamePk": 99},
              {"venue": "Brand New Park", "home_team": "TB", "gamePk": 98}]
sgv.update_park_factor_file(pf, 2027, new_season)
pf = sgv.load_park_factors()
assert pf[(2027, "Coors Field")]["park_factor"] == 1.10
assert pf[(2027, "Coors Field")]["note"] == "carried from 2025 - check FanGraphs"
assert pf[(2027, "Brand New Park")]["park_factor"] is None
assert pf[(2025, "Coors Field")]["note"] == ""

# early-season blending: weight grows with team games, 100% at BLEND_GAMES, none without a prior season
prev = {"runs_per_team_game": 4.5, "bullpen_ra9": 4.5}
early = sgv.blend_league_averages({"games": 150, "runs_per_team_game": 3.5, "bullpen_ra9": 5.5}, prev)
assert early["team_games"] == 10 and abs(early["current_weight"] - 10 / sgv.BLEND_GAMES) < 1e-3
assert abs(early["runs_per_team_game"] - (3.5 / 6 + 4.5 * 5 / 6)) < 1e-9
assert abs(early["bullpen_ra9"] - (5.5 / 6 + 4.5 * 5 / 6)) < 1e-9
full = sgv.blend_league_averages({"games": 2430, "runs_per_team_game": 4.4, "bullpen_ra9": 4.6}, prev)
assert full["current_weight"] == 1 and full["runs_per_team_game"] == 4.4
alone = sgv.blend_league_averages({"games": 150, "runs_per_team_game": 3.5, "bullpen_ra9": 5.5}, None)
assert alone["current_weight"] == 1 and alone["runs_per_team_game"] == 3.5

# ND thresholds: a new season is calibrated on earlier seasons only, then frozen
sgv.THRESHOLDS_FILE.unlink()
rng = np.random.default_rng(1)
fake = []
for season, shift in ((2025, 0.0), (2026, 0.0), (2027, 3.0)):   # 2027 behaves very differently
    x = rng.normal(0, 2, 3000)
    won = rng.random(x.size) < 1 / (1 + np.exp(-(-0.1 - 0.5 * (x - shift))))
    fake += [{"season": season, "SGV": v, "team_result": "W" if w else "L"} for v, w in zip(x, won)]
th = sgv.season_thresholds(fake, 0.40)
assert th[2025]["calibrated_on"] == "2025-2027"          # earliest season: all seasons loaded
assert th[2026]["calibrated_on"] == "2025"
assert th[2027]["calibrated_on"] == "2025-2026"          # not influenced by 2027's own data
assert abs(th[2027]["sgv_w_below"] - th[2026]["sgv_w_below"]) < 0.3
saved = dict(th[2027])
th2 = sgv.season_thresholds(fake + [{"season": 2027, "SGV": 5.0, "team_result": "W"}] * 500, 0.35)
assert th2[2027]["sgv_w_below"] == saved["sgv_w_below"] and th2[2027]["nd_band"] == 0.40  # frozen

# player photos: matched through Wikidata, credited, framed around the face, cached
photos = json.loads(ph.PHOTOS_FILE.read_text())
assert photos["10"]["img"].endswith("500px-rocky.jpg") and photos["10"]["artist"] == "Ann & Co"
assert photos["10"]["license"] == "CC BY-SA 4.0" and photos["10"]["via"] == "Wikimedia Commons"
assert photos["10"]["face"] == "auto" and photos["10"]["crop"] == ph.face_crop(200, 300, (80, 40, 120, 90))
assert photos["20"]["none"] is True
meta = json.loads(re.search(r"const META = (.*);\n", report).group(1))
assert meta["photos"] == {"10": [photos["10"]["img"], photos["10"]["page"], "Ann & Co", "CC BY-SA 4.0",
                                 "Wikimedia Commons", photos["10"]["crop"]]}
# crop maths: 2.6 x the face, a little below its centre, kept inside the image
assert ph.face_crop(200, 300, (80, 40, 120, 90)) == ph.square_crop(200, 300, 100, 65 + 0.12 * 50, 130)
assert ph.square_crop(400, 300, 390, 10, 500) == [0.25, 0.0, 0.75, 1.0]
assert ph.face_crop(400, 300, None) == [0.125, 0.0, 0.75, 1.0]          # no face: top square

# Openverse candidates: name-matched, credited, 640 px Flickr size, listed for review, not published
review = list(csv.DictReader(ph.REVIEW_FILE.open()))
pad = [r for r in review if r["mlb_id"] == "20"]
assert len(pad) == 1 and pad[0]["option"] == "1" and pad[0]["author"] == "Bo" and pad[0]["license"] == "CC BY 2.0"
assert pad[0]["image_url"].endswith("123_abc_z.jpg") and pad[0]["face"] == "yes" and pad[0]["approve"] == ""
assert {r["mlb_id"] for r in review if r["option"] == "0"} == {"30", "40"}   # searched, nothing found
assert "Pad Ace" in ph.REVIEW_PAGE.read_text() and "Ballpark at night" not in ph.REVIEW_PAGE.read_text()
assert (ph.SHEETS_DIR / "crops_01.png").exists() and (ph.SHEETS_DIR / "review_01.png").exists()
assert "20" not in meta["photos"]

# approving option 1 publishes it, framed and credited to its author
players = {"10": ("Rocky Starter", "COL"), "20": ("Pad Ace", "SD"), "30": ("Dodger Bulk", "LAD"), "40": ("Cub Ace", "CHC")}
pad[0]["approve"] = "yes"
with ph.REVIEW_FILE.open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=ph.REVIEW_COLUMNS); w.writeheader(); w.writerows(review)
table = ph.refresh(players)
assert table["20"]["via"] == "Openverse" and table["20"]["artist"] == "Bo" and table["20"]["crop"]

# a hand fix in photo_crops.csv wins over the detector
ph.CROPS_FILE.write_text("mlb_id,name,cx,cy,size\n10,Rocky Starter,0.5,0.5,0.5\n")
table = ph.refresh(players)
assert table["10"]["face"] == "manual" and table["10"]["crop"] == ph.square_crop(200, 300, 100, 150, 100)

# "skip" rejects a photo with no usable face: off the page, initials, searched on Openverse instead
ph.CROPS_FILE.write_text("mlb_id,name,cx,cy,size\n10,Rocky Starter,skip,,\n")
table = ph.refresh(players)
assert table["10"]["rejected"] is True
real_refresh = ph.refresh
ph.refresh = lambda players: ph.load_photos()        # sgv.photos is the same module
assert sgv.run([2025, 2026], 0.40, 3) is True
ph.refresh = real_refresh
meta = json.loads(re.search(r"const META = (.*);\n", sgv.REPORT_FILE.read_text()).group(1))
assert "10" not in meta["photos"] and "20" in meta["photos"]
ph.CROPS_FILE.write_text("mlb_id,name,cx,cy,size\n")
table = ph.refresh(players)
assert "rejected" not in table["10"] and table["10"]["face"] == "auto"

# inspection sheets for listed photos
import os
os.environ["SGV_INSPECT"] = "10,20"
ph.refresh(players)
assert (ph.SHEETS_DIR / "inspect_01.png").exists()
del os.environ["SGV_INSPECT"]

# already-checked pitchers aren't looked up again until 30 days have passed
calls = wiki_calls.count("sparql")
ph.refresh(players)
assert wiki_calls.count("sparql") == calls
table["30"]["checked"] = "2020-01-01"; ph.PHOTOS_FILE.write_text(json.dumps(table))
ph.refresh(players)
assert wiki_calls.count("sparql") == calls + 1
def offline(*a, **k):
    raise ph.requests.ConnectionError("no network")
ph._wiki_post = ph._wiki_get = offline
table["30"]["checked"] = "2020-01-01"; ph.PHOTOS_FILE.write_text(json.dumps(table))
assert ph.refresh(players)["10"]["img"]                  # Wikimedia down: keep what we have, no crash

shutil.rmtree(tmp)
print("ALL CHECKS PASSED")
