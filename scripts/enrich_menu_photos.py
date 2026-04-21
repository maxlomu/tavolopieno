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

def _photo_urls_from_entry(entry) -> list:
    """
    Normalize a single photo entry into a list of URLs.
    Outscraper returns photo dicts; we accept strings as a fallback.
    """
    if isinstance(entry, str):
        return [entry] if entry else []
    if not isinstance(entry, dict):
        return []

    # Try common URL-bearing keys in order of preference (original first).
    for key in ("original_photo_url", "photo_url_big", "photo_url", "url", "photo"):
        u = entry.get(key)
        if isinstance(u, str) and u:
            return [u]
    return []


def fetch_menu_photos(place_ids: list) -> dict:
    """
    Returns {place_id: [photo_url, ...]}.

    The /maps/photos-v3 endpoint returns data as a list of sublists —
    one sublist per queried place_id, in the same order as the input
    queries. Each sublist contains photo dicts. The place_id is NOT
    embedded in each photo, so we map by position.
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

    # ── Temporary diagnostics: dump the raw response shape ───────
    print("\n──── RAW RESPONSE DIAGNOSTICS ────")
    print(f"type(data)={type(data).__name__}  len={len(data) if hasattr(data, '__len__') else 'n/a'}")
    for i in range(min(2, len(data))):
        e = data[i]
        print(f"\n  data[{i}] for place_id={place_ids[i] if i < len(place_ids) else '?'}:")
        print(f"    type={type(e).__name__}")
        if isinstance(e, list):
            print(f"    len={len(e)}")
            for j, ph in enumerate(e[:3]):
                print(f"    [{j}] type={type(ph).__name__} keys={list(ph.keys()) if isinstance(ph, dict) else 'n/a'}")
                if isinstance(ph, dict):
                    print(f"         sample={json.dumps({k: str(v)[:80] for k, v in ph.items()}, ensure_ascii=False)}")
        elif isinstance(e, dict):
            print(f"    keys={list(e.keys())}")
            print(f"    sample={json.dumps({k: str(v)[:80] for k, v in e.items()}, ensure_ascii=False)}")
    print("──── END DIAGNOSTICS ────\n")

    result = {}
    for i, entry in enumerate(data):
        if i >= len(place_ids):
            break
        pid = place_ids[i]

        # Each entry is normally a list of photo dicts. Some payloads
        # wrap them in a dict with a photos_data / photos key — handle both.
        if isinstance(entry, dict):
            photos = entry.get("photos_data") or entry.get("photos") or []
        elif isinstance(entry, list):
            photos = entry
        else:
            photos = []

        urls = []
        for ph in photos:
            urls.extend(_photo_urls_from_entry(ph))

        result[pid] = urls

    total = sum(len(v) for v in result.values())
    hits = sum(1 for v in result.values() if v)
    print(f"   ✅ {hits}/{len(place_ids)} restaurants have menu photos ({total} total)")
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

    place_ids = [r["place_id"] for r in restaurants if r.get("place_id")]
    print(f"📂 Loaded {len(restaurants)} restaurants from {DATA_PATH}")

    menu_photos_by_id = fetch_menu_photos(place_ids)

    for r in restaurants:
        pid = r.get("place_id")
        photos = menu_photos_by_id.get(pid, [])
        r["menu_photos"] = photos
        r["has_menu_photos"] = len(photos) > 0

    data["menu_photos_enriched_at"] = datetime.now(timezone.utc).isoformat()

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    hits = sum(1 for r in restaurants if r["has_menu_photos"])
    print(f"\n🎯 Enriched {hits}/{len(restaurants)} restaurants with menu photos")


if __name__ == "__main__":
    main()
