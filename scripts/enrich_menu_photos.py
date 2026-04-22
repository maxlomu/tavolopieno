"""
TavoloPieno — Menu photo enrichment
===================================
Reads the existing docs/data.json (produced by fetch_restaurants.py)
and adds the "menu_photos" field to each restaurant by calling
Outscraper's /maps/photos-v3 endpoint with tag="menu" — the same
photos you see in the "Menu" tab on Google Maps.

Runs independently of the main fetcher so we don't re-scrape places
and reviews we already have.
"""

import ast
import json
import os
import sys
import time
from datetime import datetime, timezone

import requests

OUTSCRAPER_KEY = os.environ.get("OUTSCRAPER_KEY")
if not OUTSCRAPER_KEY:
    print("❌ Missing OUTSCRAPER_KEY environment variable")
    sys.exit(1)

BASE = "https://api.outscraper.cloud"
HEADERS = {"X-API-KEY": OUTSCRAPER_KEY}

DATA_PATH = "docs/data.json"
MENU_PHOTOS_PER_PLACE = 6


# ──────────────────────────────────────────────
# Outscraper async task helpers (duplicated to keep this script standalone)
# ──────────────────────────────────────────────

def wait_for_task(url: str, max_wait: int = 300) -> list:
    print(f"   ⏳ Waiting for task: {url}")
    start = time.time()
    while time.time() - start < max_wait:
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code == 200:
            data = r.json()
            status = data.get("status")
            if status == "Success":
                return data.get("data", [])
            if status in {"Failed", "Error"}:
                raise RuntimeError(f"Task failed: {data}")
        time.sleep(5)
    raise TimeoutError(f"Task timed out: {url}")


def call_async(endpoint: str, params: dict) -> list:
    r = requests.get(f"{BASE}/{endpoint}", headers=HEADERS, params=params, timeout=60)
    r.raise_for_status()
    body = r.json()
    if "results_location" in body:
        return wait_for_task(body["results_location"])
    return body.get("data", [])


# ──────────────────────────────────────────────
# Photo extraction
# ──────────────────────────────────────────────

def _coerce_photos_data(raw) -> list:
    """
    `photos_data` comes back either as a native list of dicts or as a
    Python-repr string (e.g. "[{'original_photo_url': '...'}, ...]").
    Normalize to a list of dicts.
    """
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = ast.literal_eval(raw)
            if isinstance(parsed, list):
                return parsed
        except (ValueError, SyntaxError):
            pass
    return []


def _url_from_photo(photo: dict) -> str | None:
    """Pick the best available URL from a single photo dict."""
    if not isinstance(photo, dict):
        return None
    for key in ("original_photo_url", "photo_url_big", "photo_url", "url"):
        u = photo.get(key)
        if isinstance(u, str) and u:
            return u
    return None


def fetch_menu_photos(place_ids: list) -> dict:
    """
    Returns {place_id: [photo_url, ...]}.

    The /maps/photos-v3 endpoint actually returns full place profiles
    (same shape as /maps/search-v3), one per queried place_id, in input
    order. The filtered photos live in each profile's `photos_data`
    array — when tag="menu" is set, that array is limited to photos
    from Google Maps' "Menu" tab.
    """
    print(f"🍽️  Fetching menu photos for {len(place_ids)} restaurants...")
    params = {
        "query": place_ids,
        "photosLimit": MENU_PHOTOS_PER_PLACE,
        "tag": "menu",
        "language": "it",
        "region": "IT",
        "async": "true",
    }
    data = call_async("maps/photos-v3", params)

    result = {}
    for i, entry in enumerate(data):
        if i >= len(place_ids):
            break
        pid = place_ids[i]

        # Entry is normally a 1-element list containing the place dict.
        place = None
        if isinstance(entry, list) and entry and isinstance(entry[0], dict):
            place = entry[0]
        elif isinstance(entry, dict):
            place = entry

        urls = []
        if place:
            photos_data = _coerce_photos_data(place.get("photos_data"))
            for ph in photos_data:
                u = _url_from_photo(ph)
                if u:
                    urls.append(u)

        result[pid] = urls[:MENU_PHOTOS_PER_PLACE]

    total = sum(len(v) for v in result.values())
    hits = sum(1 for v in result.values() if v)
    empties = len(place_ids) - hits
    print(f"   ✅ {hits}/{len(place_ids)} restaurants have menu photos "
          f"({total} total, {empties} with none)")
    return result


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main():
    if not os.path.exists(DATA_PATH):
        print(f"❌ {DATA_PATH} not found. Run fetch_restaurants.py first.")
        sys.exit(1)

    with open(DATA_PATH, encoding="utf-8") as f:
        data = json.load(f)

    restaurants = data.get("restaurants", [])
    if not restaurants:
        print("❌ No restaurants found in data.json")
        sys.exit(1)

    # Skip only records enriched by this (correct) version of the
    # script — we write a per-record `menu_photos_fetched_at` whenever
    # we successfully process a place. Older records that carry a stale
    # `menu_photos` field from the previous buggy run don't have this
    # timestamp, so they'll be re-processed correctly.
    total = len(restaurants)
    place_ids = [
        r["place_id"] for r in restaurants
        if r.get("place_id") and "menu_photos_fetched_at" not in r
    ]
    already = total - len(place_ids)
    print(f"📂 Loaded {total} restaurants from {DATA_PATH}")
    print(f"   → {already} already enriched (skipping), {len(place_ids)} to fetch")

    if not place_ids:
        print("✅ Nothing to do — all restaurants already have menu_photos.")
        return

    menu_photos_by_id = fetch_menu_photos(place_ids)

    # Only overwrite entries for the place_ids we actually queried. Leaves
    # any previously-enriched restaurants untouched.
    fetched_ids = set(place_ids)
    now_iso = datetime.now(timezone.utc).isoformat()
    for r in restaurants:
        pid = r.get("place_id")
        if pid in fetched_ids:
            photos = menu_photos_by_id.get(pid, [])
            r["menu_photos"] = photos
            r["has_menu_photos"] = len(photos) > 0
            r["menu_photos_fetched_at"] = now_iso

    data["menu_photos_enriched_at"] = datetime.now(timezone.utc).isoformat()

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    hits = sum(1 for r in restaurants if r["has_menu_photos"])
    print(f"\n🎯 Enriched {hits}/{len(restaurants)} restaurants with menu photos")


if __name__ == "__main__":
    main()
