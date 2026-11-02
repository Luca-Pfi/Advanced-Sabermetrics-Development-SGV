"""
Player photos for the SGV page.

1. Wikimedia Commons photos, matched through Wikidata's "MLB.com player ID"
   (P3541), so there is no guessing by name.
2. Approved Creative Commons photos from Openverse (Flickr and others): rows of
   photo_review.csv with approve = yes.
3. Face framing: every photo gets a square crop centred on the face (OpenCV's
   DNN face detector, models/), so it fills the round avatar. Hand fixes go in
   photo_crops.csv and always win.
4. Candidate search: for starters with no photo, Openverse is searched for
   freely licensed photos. Matches are written to photo_review.csv and
   photo_review.html for a person to approve; nothing from the search is
   published until approved.
5. Contact sheets in docs/photo_check/ show every crop, to check by eye.

Everything here is optional: if a service can't be reached, the run carries on
and the page keeps the initials.
"""

import csv
import hashlib
import html
import io
import json
import os
import re
import time
import unicodedata
from pathlib import Path
from urllib.parse import unquote

import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
PHOTOS_FILE = HERE / "player_photos.json"
REVIEW_FILE = HERE / "photo_review.csv"
REVIEW_PAGE = HERE / "photo_review.html"
CROPS_FILE = HERE / "photo_crops.csv"
SHEETS_DIR = HERE / "docs" / "photo_check"
IMAGE_CACHE = HERE / "cache" / "photos"
MODEL_DIR = HERE / "models"

WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
OPENVERSE_API = "https://api.openverse.org/v1/images/"
HEADERS = {"User-Agent": "SGV-leaderboards/1.0 "
                         "(https://github.com/Luca-Pfi/Advanced-Sabermetrics-Development-SGV)"}
THUMB_WIDTH = 500         # px; enough for a sharp face crop in a 92 px (184 px on retina) circle
RETRY_DAYS = 30           # pitchers without a photo are searched again after this many days
CANDIDATES_PER_PLAYER = 3
SEARCH_SECONDS = 240      # time allowed per run for the Openverse search; it resumes on the next run
FACE_PADDING = 2.6        # crop side = this × the face box, so head and shoulders fit the circle
VERSION = 2               # bump to refresh every Wikimedia entry (thumbnail size, fields)


# --------------------------------------------------------------------------
# HTTP (patched in the tests)
# --------------------------------------------------------------------------

def _wiki_post(url, data):
    r = requests.post(url, data=data, headers=HEADERS, timeout=60)
    r.raise_for_status()
    return r.json()


def _wiki_get(url, params, timeout=60):
    r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _download(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.content


def _plain(text):
    """Commons and Openverse metadata may be HTML; keep the words."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", text or ""))).strip()


def _norm(text):
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def _read_csv(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        delimiter = ";" if ";" in f.readline() else ","   # Excel in a French locale
        f.seek(0)
        return list(csv.DictReader(f, delimiter=delimiter))


# --------------------------------------------------------------------------
# 1. Wikimedia Commons through Wikidata
# --------------------------------------------------------------------------

def wikidata_images(mlb_ids):
    """MLB player id -> Commons file name."""
    found = {}
    for i in range(0, len(mlb_ids), 200):
        values = " ".join(f'"{x}"' for x in mlb_ids[i:i + 200])
        query = (f"SELECT ?id ?image WHERE {{ VALUES ?id {{ {values} }} "
                 f"?item wdt:P3541 ?id . ?item wdt:P18 ?image . }}")
        for b in _wiki_post(WIKIDATA_SPARQL, {"query": query, "format": "json"})["results"]["bindings"]:
            found.setdefault(b["id"]["value"], unquote(b["image"]["value"].rsplit("/", 1)[-1]))
    return found


def commons_info(files):
    """Commons file name -> thumbnail, file page, author and licence."""
    info = {}
    for i in range(0, len(files), 50):
        chunk = files[i:i + 50]
        data = _wiki_get(COMMONS_API, {
            "action": "query", "format": "json", "prop": "imageinfo", "iiprop": "url|extmetadata",
            "iiurlwidth": THUMB_WIDTH, "titles": "|".join(f"File:{f}" for f in chunk)})["query"]
        renamed = {n["from"]: n["to"] for n in data.get("normalized", [])}
        pages = {pg["title"]: pg for pg in data.get("pages", {}).values()}
        for f in chunk:
            page = pages.get(renamed.get(f"File:{f}", f"File:{f}"), {})
            ii = (page.get("imageinfo") or [{}])[0]
            meta = ii.get("extmetadata", {})
            if ii.get("thumburl") or ii.get("url"):
                info[f] = {"img": ii.get("thumburl") or ii["url"], "page": ii.get("descriptionurl", ""),
                           "artist": _plain(meta.get("Artist", {}).get("value"))[:80] or "Unknown author",
                           "license": _plain(meta.get("LicenseShortName", {}).get("value")) or "see file page",
                           "via": "Wikimedia Commons"}
    return info


def update_wikimedia(photos, mlb_ids, today):
    """Look up pitchers not checked yet (or with no photo for RETRY_DAYS); refresh old entries."""
    todo = [i for i in mlb_ids
            if i not in photos
            or (photos[i].get("none") and today - pd.Timestamp(photos[i]["checked"]) > pd.Timedelta(days=RETRY_DAYS))]
    stale = [i for i in mlb_ids if photos.get(i, {}).get("via", "Wikimedia Commons") == "Wikimedia Commons"
             and photos.get(i, {}).get("file") and photos[i].get("v") != VERSION]
    if not todo and not stale:
        return 0
    files = wikidata_images(todo) if todo else {}
    files.update({i: photos[i]["file"] for i in stale})
    info = commons_info(sorted(set(files.values())))
    for pid in todo + stale:
        photo = info.get(files.get(pid))
        if photo:
            keep = {k: photos[pid][k] for k in ("crop", "face", "w", "h") if k in photos.get(pid, {})
                    and photos[pid].get("img") == photo["img"]}
            photos[pid] = {**photo, "file": files[pid], "v": VERSION, **keep}
        elif pid in todo:
            photos[pid] = {"none": True, "checked": today.strftime("%Y-%m-%d")}
    return len(todo) + len(stale)


# --------------------------------------------------------------------------
# 2. Openverse candidates and approvals
# --------------------------------------------------------------------------

LICENSE_NAMES = {"cc0": "CC0", "pdm": "Public Domain Mark", "by": "CC BY", "by-sa": "CC BY-SA"}
REVIEW_COLUMNS = ["mlb_id", "name", "team", "option", "approve", "author", "license", "title",
                  "landing_url", "image_url", "face", "searched"]


def _approved(row):
    return (row.get("approve") or "").strip().lower() in ("yes", "y", "x", "1", "true", "oui")


def openverse_search(name):
    """Freely licensed photographs whose title or tags carry the pitcher's first and last name."""
    data = _wiki_get(OPENVERSE_API, {"q": name, "license": "cc0,pdm,by,by-sa", "category": "photograph",
                                     "page_size": 20, "mature": "false"}, timeout=90)
    parts = [p for p in _norm(name).replace(".", " ").split() if len(p) > 1]
    first, last = parts[0], parts[-1]
    hits = []
    for r in data.get("results", []):
        words = _norm(" ".join([r.get("title") or ""] + [t.get("name", "") for t in r.get("tags") or []]))
        if first in words and last in words and r.get("url"):
            hits.append(r)
    return hits


def _sized_flickr(url):
    """Flickr large (_b, _c, _h, _k) -> 640 px (_z); other hosts unchanged."""
    return re.sub(r"(staticflickr\.com/.+_[0-9a-f]+)_[bchk]\.jpg$", r"\1_z.jpg", url)


def _save_review(rows):
    rows.sort(key=lambda r: (r["name"], int(r["option"] or 0)))
    with REVIEW_FILE.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REVIEW_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def search_candidates(photos, players, today, budget, seconds=SEARCH_SECONDS):
    """Search Openverse for starters with no photo, at most `budget` pitchers or `seconds` per run.

    Each pitcher's results are saved as soon as they are found, so the next run resumes where this one stopped.
    """
    deadline = time.monotonic() + seconds
    rows = _read_csv(REVIEW_FILE)
    searched = {}
    for r in rows:
        searched[r["mlb_id"]] = max(searched.get(r["mlb_id"], ""), r.get("searched") or "")
    missing = [pid for pid in players if (photos.get(pid, {}).get("none") or photos.get(pid, {}).get("rejected"))
               and not any(_approved(r) for r in rows if r["mlb_id"] == pid)
               and (pid not in searched
                    or today - pd.Timestamp(searched[pid] or "2000-01-01") > pd.Timedelta(days=RETRY_DAYS))]
    added, failures = 0, 0
    for pid in missing[:budget]:
        if time.monotonic() > deadline:
            print(f"Photo candidates: time limit reached, {len(missing) - added} starters left for the next runs")
            break
        name, team = players[pid]
        try:
            try:
                hits = openverse_search(name)
            except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as e:
                if isinstance(e, requests.HTTPError) and (e.response is None or e.response.status_code < 500):
                    raise
                time.sleep(5)                     # Openverse sometimes answers 5xx or slowly: one retry
                hits = openverse_search(name)
            failures = 0
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else "?"
            if isinstance(status, int) and status >= 500:
                failures += 1                     # server error: skip this pitcher, three in a row end the search
                print(f"  Openverse error {status} for {name}; skipped this run")
                if failures >= 3:
                    print("Openverse keeps failing; the search continues on the next run")
                    break
                continue
            if status == 429:
                print("Openverse rate limit reached; the search continues on the next run")
            else:
                body = (e.response.text if e.response is not None else "")[:300].replace("\n", " ")
                print(f"Openverse refused the search (HTTP {status}): {body}")
            break
        except (requests.Timeout, requests.ConnectionError):
            failures += 1          # a slow answer skips this pitcher; three in a row end this run's search
            if failures >= 3:
                print("Openverse not answering; the search continues on the next run")
                break
            continue
        found = []
        for r in hits:
            url = _sized_flickr(r["url"])
            try:
                img = load_image(url)
            except (requests.RequestException, ValueError):
                continue
            face = detect_face(img)
            found.append({"r": r, "url": url, "face": face is not None})
            if len([f for f in found if f["face"]]) >= CANDIDATES_PER_PLAYER:
                break
        found.sort(key=lambda f: not f["face"])
        rows = [r for r in rows if r["mlb_id"] != pid or _approved(r)]
        stamp = today.strftime("%Y-%m-%d")
        if not found:
            rows.append({"mlb_id": pid, "name": name, "team": team, "option": "0", "approve": "",
                         "title": "(no match found)", "searched": stamp})
        for n, f in enumerate(found[:CANDIDATES_PER_PLAYER], 1):
            r = f["r"]
            version = f" {r['license_version']}" if r.get("license_version") and r["license"] not in ("pdm",) else ""
            rows.append({"mlb_id": pid, "name": name, "team": team, "option": str(n), "approve": "",
                         "author": _plain(r.get("creator")) or "Unknown author",
                         "license": LICENSE_NAMES.get(r["license"], r["license"].upper()) + version,
                         "title": _plain(r.get("title"))[:120], "landing_url": r.get("foreign_landing_url", ""),
                         "image_url": f["url"], "face": "yes" if f["face"] else "no", "searched": stamp})
        added += 1
        _save_review(rows)
        time.sleep(1.0)   # be polite to the anonymous API
    return added


def apply_approvals(photos):
    """Approved Openverse photos become the pitcher's photo (they also replace a Wikimedia one)."""
    changed = 0
    for r in _read_csv(REVIEW_FILE):
        if not _approved(r) or not r.get("image_url"):
            continue
        entry = {"img": r["image_url"], "page": r.get("landing_url", ""), "artist": r.get("author") or "Unknown author",
                 "license": r.get("license") or "see source", "via": "Openverse", "option": r["option"]}
        current = photos.get(r["mlb_id"], {})
        if current.get("img") != entry["img"]:
            photos[r["mlb_id"]] = entry
            changed += 1
    return changed


# --------------------------------------------------------------------------
# 3. Face framing
# --------------------------------------------------------------------------

_net = None
_offline = False   # set when an image host can't be reached at all: stop trying for this run


def load_image(url):
    """Image as an OpenCV BGR array, cached on disk (the workflow keeps cache/ between runs)."""
    import cv2
    import numpy as np
    IMAGE_CACHE.mkdir(parents=True, exist_ok=True)
    path = IMAGE_CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".img")
    if not path.exists():
        global _offline
        if _offline:
            raise requests.ConnectionError("image hosts not reachable")
        try:
            path.write_bytes(_download(url))
        except requests.ConnectionError:
            _offline = True
            raise
    img = cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"not an image: {url}")
    return img


def detect_face(img):
    """Most likely face box (x1, y1, x2, y2) in pixels, or None."""
    import cv2
    global _net
    if _net is None:
        _net = cv2.dnn.readNetFromCaffe(str(MODEL_DIR / "deploy.prototxt"),
                                        str(MODEL_DIR / "res10_300x300_ssd_iter_140000_fp16.caffemodel"))
    h, w = img.shape[:2]
    best = None
    # The model is trained at 300x300; a second pass near native size finds the small faces of action shots.
    scale = 640 / max(h, w)
    for size in ((300, 300), (max(64, int(w * scale) // 32 * 32), max(64, int(h * scale) // 32 * 32))):
        blob = cv2.dnn.blobFromImage(cv2.resize(img, size), 1.0, size, (104.0, 177.0, 123.0))
        _net.setInput(blob)
        det = _net.forward()
        for i in range(det.shape[2]):
            conf = float(det[0, 0, i, 2])
            if conf < 0.55:
                continue
            x1, y1, x2, y2 = (det[0, 0, i, 3:7] * [w, h, w, h]).tolist()
            x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
            if x2 - x1 < 8 or y2 - y1 < 8:
                continue
            score = conf * ((x2 - x1) * (y2 - y1) / (w * h)) ** 0.25
            if best is None or score > best[0]:
                best = (score, (x1, y1, x2, y2))
    return best[1] if best else None


def square_crop(w, h, cx, cy, side):
    """Square crop of `side` px centred on (cx, cy), kept inside the image; as fractions [L, T, W, H]."""
    side = max(1.0, min(side, w, h))
    left = min(max(cx - side / 2, 0), w - side)
    top = min(max(cy - side / 2, 0), h - side)
    return [round(left / w, 4), round(top / h, 4), round(side / w, 4), round(side / h, 4)]


def face_crop(w, h, box):
    if box is None:
        # No face found: a full-height (or full-width) square from the top, where heads usually are.
        side = min(w, h)
        return square_crop(w, h, w / 2, side / 2, side)
    x1, y1, x2, y2 = box
    fw, fh = x2 - x1, y2 - y1
    return square_crop(w, h, (x1 + x2) / 2, (y1 + y2) / 2 + 0.12 * fh, FACE_PADDING * max(fw, fh))


def manual_crops():
    """photo_crops.csv: mlb_id, name, cx, cy, size (fractions of image width/height; size of the width).

    cx = "skip" rejects the photo (no usable face): the card keeps the initials and the
    pitcher is searched on Openverse like one with no photo.
    """
    out = {}
    for r in _read_csv(CROPS_FILE):
        if (r.get("cx") or "").strip().lower() == "skip":
            out[r["mlb_id"]] = "skip"
            continue
        try:
            out[r["mlb_id"]] = tuple(float(str(r[k]).replace(",", ".")) for k in ("cx", "cy", "size"))
        except (KeyError, ValueError):
            continue
    return out


def frame_photos(photos):
    """Give every photo a face crop; hand fixes in photo_crops.csv override the detector."""
    try:
        import cv2  # noqa: F401
    except ImportError:
        print("Photo framing skipped: opencv-python-headless is not installed")
        return 0
    fixes = manual_crops()
    framed = 0
    for pid, p in photos.items():
        if not p.get("img"):
            continue
        fix = fixes.get(pid)
        if fix == "skip":
            framed += not p.get("rejected")
            p["rejected"] = True
            continue
        if p.pop("rejected", None):
            framed += 1
        if fix is None and p.get("crop") and p.get("face") != "manual":
            continue
        if fix is not None and p.get("face") == "manual" and p.get("fix") == list(fix):
            continue
        try:
            img = load_image(p["img"])
        except requests.ConnectionError:
            print("Photo framing stopped: image hosts not reachable")
            break
        except (requests.RequestException, ValueError) as e:
            print(f"  photo {pid}: {e.__class__.__name__}, keeping the initials")
            continue
        h, w = img.shape[:2]
        if fix is not None:
            cx, cy, size = fix
            p["crop"] = square_crop(w, h, cx * w, cy * h, size * w)
            p["face"], p["fix"] = "manual", list(fix)
        else:
            box = detect_face(img)
            p["crop"] = face_crop(w, h, box)
            p["face"] = "auto" if box else "none"
            p.pop("fix", None)
        p["w"], p["h"] = w, h
        framed += 1
    return framed


# --------------------------------------------------------------------------
# 4. Contact sheets and the review page
# --------------------------------------------------------------------------

def _font(size):
    from PIL import ImageFont
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf"):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def _crop_image(url, crop, side):
    """The circle crop as a PIL image, side x side px."""
    import cv2
    from PIL import Image, ImageDraw
    img = load_image(url)
    h, w = img.shape[:2]
    left, top, cw, ch = crop
    x, y, s = int(left * w), int(top * h), max(1, int(cw * w))
    sq = cv2.cvtColor(img[y:y + s, x:x + s], cv2.COLOR_BGR2RGB)
    pic = Image.fromarray(sq).resize((side, side))
    mask = Image.new("L", (side, side), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, side - 1, side - 1), fill=255)
    out = Image.new("RGB", (side, side), "white")
    out.paste(pic, (0, 0), mask)
    return out


def contact_sheets(photos, players):
    """docs/photo_check/crops_NN.png: every photo's circle crop, 8 x 6 per sheet, to check by eye."""
    from PIL import Image, ImageDraw
    SHEETS_DIR.mkdir(parents=True, exist_ok=True)
    for old in SHEETS_DIR.glob("crops_*.png"):
        old.unlink()
    items = sorted((players.get(pid, ("?", ""))[0], pid) for pid, p in photos.items()
                   if p.get("img") and p.get("crop") and pid in players)
    cols, rows_, cell, side = 8, 6, 150, 112
    font, small = _font(13), _font(11)
    for page in range(0, len(items), cols * rows_):
        chunk = items[page:page + cols * rows_]
        sheet = Image.new("RGB", (cols * cell, ((len(chunk) - 1) // cols + 1) * (side + 52)), "white")
        d = ImageDraw.Draw(sheet)
        for k, (name, pid) in enumerate(chunk):
            p = photos[pid]
            x, y = (k % cols) * cell + (cell - side) // 2, (k // cols) * (side + 52) + 6
            try:
                sheet.paste(_crop_image(p["img"], p["crop"], side), (x, y))
            except (requests.RequestException, ValueError):
                d.ellipse((x, y, x + side, y + side), outline="red", width=3)
            ring = {"auto": "#4499aa", "manual": "#2a9d3a", "none": "#d82129"}.get(p.get("face"), "#999999")
            d.ellipse((x, y, x + side, y + side), outline=ring, width=3)
            d.text((x + side // 2, y + side + 6), name[:22], fill="black", font=font, anchor="ma")
            d.text((x + side // 2, y + side + 24), f"{pid} · {p.get('face', '?')}", fill="#666666", font=small, anchor="ma")
        sheet.save(SHEETS_DIR / f"crops_{page // (cols * rows_) + 1:02d}.png", optimize=True)


def inspect_sheets(photos, players, ids):
    """docs/photo_check/inspect_NN.png: full photos with a 10% grid, the detected face (red) and
    the crop (cyan), to place hand fixes in photo_crops.csv."""
    import cv2
    from PIL import Image, ImageDraw
    for old in SHEETS_DIR.glob("inspect_*.png"):
        old.unlink()
    ids = [i for i in ids if photos.get(i, {}).get("img")]
    cell_w, cell_h, per_page = 560, 470, 6
    font, small = _font(15), _font(11)
    for page in range(0, len(ids), per_page):
        chunk = ids[page:page + per_page]
        sheet = Image.new("RGB", (2 * cell_w, ((len(chunk) + 1) // 2) * cell_h), "white")
        d = ImageDraw.Draw(sheet)
        for k, pid in enumerate(chunk):
            p = photos[pid]
            ox, oy = (k % 2) * cell_w + 10, (k // 2) * cell_h + 8
            d.text((ox, oy), f"{players.get(pid, ('?', ''))[0]} · {pid} · {p.get('face', '?')}", fill="black", font=font)
            try:
                img = load_image(p["img"])
            except (requests.RequestException, ValueError):
                continue
            h, w = img.shape[:2]
            scale = min((cell_w - 40) / w, (cell_h - 50) / h)
            pic = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)).resize((int(w * scale), int(h * scale)))
            px, py = ox + 22, oy + 26
            sheet.paste(pic, (px, py))
            W, H = pic.size
            for t in range(1, 10):
                d.line((px + W * t / 10, py, px + W * t / 10, py + H), fill=(255, 255, 0), width=1)
                d.line((px, py + H * t / 10, px + W, py + H * t / 10), fill=(255, 255, 0), width=1)
                d.text((px + W * t / 10, py - 1), f".{t}", fill="#555555", font=small, anchor="mb")
                d.text((px - 3, py + H * t / 10), f".{t}", fill="#555555", font=small, anchor="rm")
            box = detect_face(img)
            if box:
                d.rectangle([px + box[0] * scale, py + box[1] * scale, px + box[2] * scale, py + box[3] * scale], outline="red", width=2)
            if p.get("crop"):
                L, T, CW, CH = p["crop"]
                d.rectangle([px + L * W, py + T * H, px + (L + CW) * W, py + (T + CH) * H], outline=(0, 200, 255), width=3)
        sheet.save(SHEETS_DIR / f"inspect_{page // per_page + 1:02d}.png", optimize=True)


def review_sheets():
    """docs/photo_check/review_NN.png: Openverse candidates per pitcher, numbered, to check identities."""
    from PIL import Image, ImageDraw
    for old in SHEETS_DIR.glob("review_*.png"):
        old.unlink()
    rows = [r for r in _read_csv(REVIEW_FILE) if r.get("image_url")]
    by_player = {}
    for r in rows:
        by_player.setdefault((r["name"], r["mlb_id"]), []).append(r)
    people = sorted(by_player)
    side, label_w, per_page = 150, 230, 10
    font, small = _font(14), _font(11)
    for page in range(0, len(people), per_page):
        chunk = people[page:page + per_page]
        sheet = Image.new("RGB", (label_w + CANDIDATES_PER_PLAYER * (side + 16) + 10, len(chunk) * (side + 34) + 10), "white")
        d = ImageDraw.Draw(sheet)
        for k, key in enumerate(chunk):
            y = 10 + k * (side + 34)
            name, pid = key
            d.text((8, y + 10), name, fill="black", font=font)
            d.text((8, y + 32), f"{pid} · {by_player[key][0]['team']}", fill="#666666", font=small)
            for j, r in enumerate(by_player[key][:CANDIDATES_PER_PLAYER]):
                x = label_w + j * (side + 16)
                try:
                    img = load_image(r["image_url"])
                    h, w = img.shape[:2]
                    crop = face_crop(w, h, detect_face(img))
                    sheet.paste(_crop_image(r["image_url"], crop, side), (x, y))
                except (requests.RequestException, ValueError):
                    d.rectangle((x, y, x + side, y + side), outline="red", width=2)
                d.text((x + 4, y + side + 4), f"option {r['option']} · face {r['face']}", fill="#333333", font=small)
        sheet.save(SHEETS_DIR / f"review_{page // per_page + 1:02d}.png", optimize=True)


def review_page():
    """photo_review.html: the candidates with credits, for approving in photo_review.csv."""
    rows = [r for r in _read_csv(REVIEW_FILE) if r.get("image_url")]
    by_player = {}
    for r in rows:
        by_player.setdefault((r["name"], r["mlb_id"], r["team"]), []).append(r)
    cards = []
    for (name, pid, team), opts in sorted(by_player.items()):
        cells = "".join(
            f'<figure><a href="{html.escape(r["landing_url"])}" target="_blank" rel="noopener">'
            f'<img src="{html.escape(r["image_url"])}" alt="Option {r["option"]} for {html.escape(name)}" loading="lazy"></a>'
            f'<figcaption><b>Option {r["option"]}</b>{" · approved" if _approved(r) else ""}<br>'
            f'{html.escape(r["author"])} · {html.escape(r["license"])}<br><small>{html.escape(r["title"])}</small></figcaption></figure>'
            for r in opts)
        cards.append(f'<section><h2>{html.escape(name)} <span>{html.escape(team)} · MLB ID {pid}</span></h2>'
                     f'<div class="opts">{cells}</div></section>')
    REVIEW_PAGE.write_text(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>SGV Photo Review</title>
<style>
:root {{ color-scheme: light dark; --b: #4499aa; }}
body {{ margin: 0; font: 15px/1.4 "Roboto Condensed", Arial, sans-serif; background: Canvas; color: CanvasText; }}
main {{ max-width: 1100px; margin: 0 auto; padding: 20px 16px 40px; }}
h1 {{ margin: 0 0 6px; }} p {{ max-width: 75ch; }}
section {{ border: 1px solid var(--b); padding: 10px 14px; margin: 14px 0; }}
h2 {{ margin: 0 0 8px; font-size: 20px; }} h2 span {{ font-weight: 400; font-size: 14px; opacity: .7; }}
.opts {{ display: flex; gap: 14px; flex-wrap: wrap; }}
figure {{ margin: 0; width: 220px; }} figure img {{ width: 220px; height: 220px; object-fit: cover; display: block; }}
figcaption {{ font-size: 13px; margin-top: 4px; overflow-wrap: anywhere; }}
</style></head><body><main>
<h1>Photo candidates</h1>
<p>Freely licensed photos (Creative Commons or public domain) found on Openverse for starters who have no
Wikipedia photo. They were matched by name only, so check that each one shows the right pitcher.
To use one, open <code>photo_review.csv</code> in the repository, put <b>yes</b> in the <code>approve</code>
column of that option's row and commit. The next daily update frames it and puts it on the leaderboards page,
credited to its author. Nothing here is published on the leaderboards until approved.</p>
{''.join(cards) or '<p>No candidates yet.</p>'}
</main></body></html>
""", encoding="utf-8")


# --------------------------------------------------------------------------
# All steps
# --------------------------------------------------------------------------

def load_photos():
    return json.loads(PHOTOS_FILE.read_text()) if PHOTOS_FILE.exists() else {}


def refresh(players, search_budget=60):
    """players: {mlb_id: (name, team)} for every starter on the page. Returns the photo table."""
    players = {str(k): v for k, v in players.items()}
    photos = load_photos()
    before = json.dumps(photos, sort_keys=True)
    today = pd.Timestamp.today().normalize()
    try:
        n = update_wikimedia(photos, sorted(players), today)
        if n:
            print(f"Player photos: {n} starters checked on Wikimedia, "
                  f"{sum(1 for p in photos.values() if p.get('img'))} have a photo")
    except (requests.RequestException, ValueError, KeyError) as e:
        print(f"Wikimedia photos skipped, not reachable ({e.__class__.__name__})")
    approved = apply_approvals(photos)
    if approved:
        print(f"Player photos: {approved} approved Openverse photos applied")
    framed = frame_photos(photos)
    if framed:
        print(f"Player photos: {framed} photos framed around the face")
    found = 0
    if search_budget:
        try:
            found = search_candidates(photos, players, today, search_budget)
            if found:
                print(f"Photo candidates: {found} starters searched on Openverse (see photo_review.csv)")
        except (requests.RequestException, ValueError, KeyError) as e:
            print(f"Openverse search skipped, not reachable ({e.__class__.__name__})")
        except ImportError:
            print("Openverse search skipped: opencv-python-headless is not installed")
    changed = json.dumps(photos, sort_keys=True) != before
    if changed:
        PHOTOS_FILE.write_text(json.dumps(photos, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    if (changed or found or not SHEETS_DIR.exists()) and not _offline:
        try:
            contact_sheets(photos, players)
            review_sheets()
        except ImportError:
            pass
    # Photos to look at closely: no face found, plus any listed in SGV_INSPECT (comma-separated MLB ids).
    extra = [i.strip() for i in os.environ.get("SGV_INSPECT", "").split(",") if i.strip()]
    look = sorted({pid for pid, p in photos.items() if p.get("face") == "none" and not p.get("rejected")} | set(extra))
    if (changed or extra) and not _offline:
        try:
            inspect_sheets(photos, players, look)
        except ImportError:
            pass
        review_page()
    return photos
