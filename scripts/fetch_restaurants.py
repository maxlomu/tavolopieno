"""
TavoloPieno — Bari restaurants fetcher
======================================
Uses Outscraper /maps/search-v3 to fetch N restaurants in the target
city with their Google Maps profile data (rating, review count,
website, phone, cover photo, etc.) and writes docs/data.json.

This script does NOT fetch individual reviews anymore — review fetching
is expensive ($3 / 1000) and only needed for trend analysis, which has
moved to scripts/analyze_trend.py (triggered per-restaurant on demand
via the dashboard). A base run here costs roughly $0.003 × N places.
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

CITY = "Bari, Italy"
QUERY = f"ristoranti {CITY}"
N_RESTAURANTS = 100


# ──────────────────────────────────────────────
# Outscraper async task helpers
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
# Fetch
# ──────────────────────────────────────────────

def fetch_restaurants() -> list:
    print(f"🔍 Searching: {QUERY}")
    params = {
        "query": QUERY,
        "limit": N_RESTAURANTS,
        "language": "it",
        "region": "IT",
        "async": "true",
    }
    data = call_async("maps/search-v3", params)
    if data and isinstance(data[0], list):
        places = data[0]
    else:
        places = data
    print(f"   ✅ Got {len(places)} restaurants")
    return places[:N_RESTAURANTS]


# ──────────────────────────────────────────────
# Scoring (rating + volume only; trend is added later by analyze_trend.py)
# ──────────────────────────────────────────────

def score_restaurant(place: dict) -> dict:
    """
    Base pain score using only the place-level rating and review count.
    Range: 0–80 (trend_pain of 0–20 is added by analyze_trend.py when
    the user explicitly analyzes a single restaurant).
    """
    rating = place.get("rating", 0) or 0
    count = place.get("reviews", 0) or 0

    # Rating pain (0–50): sweet spot is 3.5–4.2
    if rating == 0:
        rating_pain = 30
    elif rating < 3.0:
        rating_pain = 15
    elif rating <= 3.5:
        rating_pain = 50
    elif rating <= 4.0:
        rating_pain = 40
    elif rating <= 4.2:
        rating_pain = 30
    elif rating <= 4.5:
        rating_pain = 15
    else:
        rating_pain = 5

    # Volume pain (0–30): low review count = low visibility
    if count < 10:
        volume_pain = 30
    elif count < 30:
        volume_pain = 20
    elif count < 100:
        volume_pain = 10
    else:
        volume_pain = 0

    score = rating_pain + volume_pain
    tier = (
        "Hot Lead"    if score >= 70 else
        "Warm Lead"   if score >= 50 else
        "Nurture"     if score >= 30 else
        "Low Priority"
    )
    return {
        "score": score,
        "tier": tier,
        "rating_pain": rating_pain,
        "volume_pain": volume_pain,
        "trend_pain": 0,
        "trend": "unknown",           # set by analyze_trend.py
        "trend_analyzed": False,      # flips to True after analyze_trend runs
    }


# ──────────────────────────────────────────────
# Merge helpers
# ──────────────────────────────────────────────

# Fields written by the various enrichment scripts. We must preserve
# these when re-running the base fetcher so a refresh doesn't nuke
# paid-for enrichment data.
ENRICHED_FIELDS = (
    # menu photos
    "menu_photos", "has_menu_photos",
    # contacts
    "primary_email", "primary_contact_name", "primary_contact_title",
    "all_emails", "contacts",
    # trend analysis (per-restaurant)
    "trend_analyzed", "trend_analyzed_at", "trend", "trend_pain",
    "sample_reviews",
)


def load_existing_records() -> dict:
    """Return {place_id: restaurant_dict} from the prior data.json, or {}."""
    if not os.path.exists("docs/data.json"):
        return {}
    try:
        with open("docs/data.json", encoding="utf-8") as f:
            old = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    return {r["place_id"]: r for r in old.get("restaurants", []) if r.get("place_id")}


def apply_trend_to_score(record: dict) -> None:
    """If trend_pain is set, fold it into score and re-derive tier."""
    if not record.get("trend_analyzed"):
        return
    trend_pain = record.get("trend_pain") or 0
    if trend_pain <= 0:
        return
    base = (record.get("rating_pain") or 0) + (record.get("volume_pain") or 0)
    total = min(100, base + trend_pain)
    record["score"] = total
    record["tier"] = (
        "Hot Lead"    if total >= 70 else
        "Warm Lead"   if total >= 50 else
        "Nurture"     if total >= 30 else
        "Low Priority"
    )


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main():
    places = fetch_restaurants()
    if not places:
        print("❌ No places returned")
        sys.exit(1)

    existing = load_existing_records()
    if existing:
        print(f"   🗃️  Preserving enrichment data from {len(existing)} existing records")

    results = []
    for p in places:
        pid = p.get("place_id") or p.get("google_id")
        scoring = score_restaurant(p)

        record = {
            "place_id":      pid,
            "name":          p.get("name", ""),
            "address":       p.get("full_address") or p.get("address", ""),
            "phone":         p.get("phone", ""),
            "website":       p.get("site") or p.get("website", ""),
            "maps_url":      p.get("location_link") or f"https://www.google.com/maps/place/?q=place_id:{pid}",
            "rating":        p.get("rating", 0),
            "review_count":  p.get("reviews", 0),
            "price_level":   p.get("range") or p.get("price_level"),
            "category":      p.get("type") or p.get("category"),
            "photo":         p.get("photo"),
            **scoring,
        }

        # Re-apply any prior enrichment so we don't lose paid-for data
        prior = existing.get(pid)
        if prior:
            for key in ENRICHED_FIELDS:
                if key in prior:
                    record[key] = prior[key]
            apply_trend_to_score(record)

        results.append(record)

    # Sort by score descending
    results.sort(key=lambda x: x["score"], reverse=True)

    output = {
        "city":        CITY,
        "query":       QUERY,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count":       len(results),
        "restaurants": results,
    }

    os.makedirs("docs", exist_ok=True)
    with open("docs/data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n🎯 Saved {len(results)} restaurants to docs/data.json")
    print(f"   Hot Leads:  {sum(1 for r in results if r['tier'] == 'Hot Lead')}")
    print(f"   Warm Leads: {sum(1 for r in results if r['tier'] == 'Warm Lead')}")
    print(f"\n💡 To add trend analysis for a specific restaurant, run the")
    print(f"   'Analizza trend recensioni' workflow with its place_id.")


if __name__ == "__main__":
    main()
