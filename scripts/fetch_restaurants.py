"""
TavoloPieno — Bari restaurants fetcher
======================================
Uses Outscraper to fetch 10 restaurants in Bari + their reviews,
detects whether any review includes a photo (menu candidate),
and saves everything to docs/data.json for the dashboard to read.
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
N_RESTAURANTS = 10
REVIEWS_PER_PLACE = 20  # enough to find photos if any exist


# ──────────────────────────────────────────────
# Outscraper async task helpers
# ──────────────────────────────────────────────

def wait_for_task(url: str, max_wait: int = 300) -> list:
    """Poll an async task until finished. Returns the data list."""
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
    """Call Outscraper endpoint, handle async response."""
    r = requests.get(f"{BASE}/{endpoint}", headers=HEADERS, params=params, timeout=60)
    r.raise_for_status()
    body = r.json()

    # If async, follow the results URL
    if "results_location" in body:
        return wait_for_task(body["results_location"])
    # If sync, data is inline under "data"
    return body.get("data", [])


# ──────────────────────────────────────────────
# Fetchers
# ──────────────────────────────────────────────

def fetch_restaurants() -> list:
    """Get N restaurants matching the query."""
    print(f"🔍 Searching: {QUERY}")
    params = {
        "query": QUERY,
        "limit": N_RESTAURANTS,
        "language": "it",
        "region": "IT",
        "async": "true",
    }
    data = call_async("maps/search-v3", params)
    # Data comes back nested: [[{place1}, {place2}, ...]]
    if data and isinstance(data[0], list):
        places = data[0]
    else:
        places = data
    print(f"   ✅ Got {len(places)} restaurants")
    return places[:N_RESTAURANTS]


def fetch_reviews(place_ids: list) -> dict:
    """Get reviews (with photos) for a list of place_ids. Returns {place_id: [reviews]}."""
    print(f"💬 Fetching reviews for {len(place_ids)} restaurants...")
    params = {
        "query": place_ids,  # requests will repeat the param for each id
        "reviewsLimit": REVIEWS_PER_PLACE,
        "language": "it",
        "async": "true",
        "sort": "newest",
    }
    data = call_async("maps/reviews-v3", params)
    # data is a list of places, each with a reviews_data array
    result = {}
    for place in data:
        pid = place.get("place_id") or place.get("google_id")
        if pid:
            result[pid] = place.get("reviews_data", [])
    print(f"   ✅ Got reviews for {len(result)} places")
    return result


# ──────────────────────────────────────────────
# Scoring
# ──────────────────────────────────────────────

def score_restaurant(place: dict, reviews: list) -> dict:
    """
    Simple review-focused score for v1.
    0–100, higher = more pain = better lead.
    """
    rating = place.get("rating", 0) or 0
    count = place.get("reviews", 0) or 0

    # Rating pain (0–50): sweet spot is 3.5–4.2
    if rating == 0:
        rating_pain = 30
    elif rating < 3.0:
        rating_pain = 15   # too far gone
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

    # Trend pain (0–20): last 5 reviews vs overall rating
    trend_pain = 0
    if len(reviews) >= 5:
        recent = [r.get("review_rating", rating) for r in reviews[:5]]
        recent_avg = sum(recent) / len(recent)
        if recent_avg < rating - 0.5:
            trend_pain = 20
        elif recent_avg < rating - 0.2:
            trend_pain = 10

    score = min(100, rating_pain + volume_pain + trend_pain)
    tier = (
        "Hot Lead"    if score >= 70 else
        "Warm Lead"   if score >= 50 else
        "Nurture"     if score >= 30 else
        "Low Priority"
    )

    return {"score": score, "tier": tier, "trend": "declining" if trend_pain >= 10 else "stable"}


def analyze_menu_photos(reviews: list) -> dict:
    """Check if any review includes photos (menu candidate)."""
    total_photos = 0
    reviews_with_photos = 0
    sample_photo_url = None

    for rev in reviews:
        photos = rev.get("review_photos") or rev.get("photos") or []
        if photos:
            reviews_with_photos += 1
            total_photos += len(photos)
            if not sample_photo_url:
                if isinstance(photos[0], dict):
                    sample_photo_url = photos[0].get("url") or photos[0].get("photo_url")
                else:
                    sample_photo_url = photos[0]

    return {
        "has_photos_in_reviews": reviews_with_photos > 0,
        "reviews_with_photos": reviews_with_photos,
        "total_photos": total_photos,
        "sample_photo_url": sample_photo_url,
    }


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main():
    places = fetch_restaurants()
    if not places:
        print("❌ No places returned")
        sys.exit(1)

    place_ids = [p.get("place_id") or p.get("google_id") for p in places if p.get("place_id") or p.get("google_id")]
    reviews_by_id = fetch_reviews(place_ids)

    results = []
    for p in places:
        pid = p.get("place_id") or p.get("google_id")
        reviews = reviews_by_id.get(pid, [])

        scoring = score_restaurant(p, reviews)
        photos = analyze_menu_photos(reviews)

        # Pick 2 sample recent review snippets
        sample_reviews = []
        for rev in reviews[:3]:
            text = rev.get("review_text") or ""
            if text:
                sample_reviews.append({
                    "rating": rev.get("review_rating"),
                    "text": text[:200],
                    "date": rev.get("review_datetime_utc") or rev.get("review_date"),
                })

        results.append({
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
            **photos,
            "sample_reviews": sample_reviews,
        })

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
    print(f"   With photos in reviews: {sum(1 for r in results if r['has_photos_in_reviews'])}")
    print(f"   Hot Leads:  {sum(1 for r in results if r['tier'] == 'Hot Lead')}")
    print(f"   Warm Leads: {sum(1 for r in results if r['tier'] == 'Warm Lead')}")


if __name__ == "__main__":
    main()
