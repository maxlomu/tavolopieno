"""
TavoloPieno — Per-restaurant trend analysis
===========================================
Fetches the last N reviews for a single place_id and computes:
  - trend_pain (0–20) — are recent ratings trending below the overall?
  - trend       — "declining" / "stable"
  - sample_reviews — 3 most recent reviews with text

Runs on demand via .github/workflows/analyze_trend.yml, triggered from
the "Analizza trend" button on each restaurant's row in the dashboard.

This is the former review-fetching code from fetch_restaurants.py,
moved here so the base fetch no longer pays $3/1000 for reviews on
restaurants the user isn't actually evaluating yet.
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
REVIEWS_PER_PLACE = 20  # how many recent reviews to pull


# ──────────────────────────────────────────────
# Outscraper async helpers
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
# Trend scoring (ported from the original fetch_restaurants.py)
# ──────────────────────────────────────────────

def fetch_reviews_for(place_id: str) -> list:
    print(f"💬 Fetching {REVIEWS_PER_PLACE} reviews for {place_id}...")
    params = {
        "query": place_id,
        "reviewsLimit": REVIEWS_PER_PLACE,
        "language": "it",
        "async": "true",
        "sort": "newest",
    }
    data = call_async("maps/reviews-v3", params)
    # data may be [place_dict] or [[place_dict]]
    if data and isinstance(data[0], list) and data[0]:
        place = data[0][0] if isinstance(data[0][0], dict) else None
    elif data and isinstance(data[0], dict):
        place = data[0]
    else:
        place = None
    reviews = place.get("reviews_data", []) if place else []
    print(f"   ✅ Got {len(reviews)} reviews")
    return reviews


def compute_trend(overall_rating: float, reviews: list) -> dict:
    """
    Trend pain (0–20): last 5 review ratings vs overall.
    Returns {trend, trend_pain}.
    """
    if len(reviews) < 5:
        return {"trend": "unknown", "trend_pain": 0}
    recent = [r.get("review_rating", overall_rating) for r in reviews[:5]]
    recent = [x for x in recent if isinstance(x, (int, float))]
    if len(recent) < 5:
        return {"trend": "unknown", "trend_pain": 0}
    recent_avg = sum(recent) / len(recent)
    if recent_avg < overall_rating - 0.5:
        return {"trend": "declining", "trend_pain": 20}
    if recent_avg < overall_rating - 0.2:
        return {"trend": "declining", "trend_pain": 10}
    return {"trend": "stable", "trend_pain": 0}


def build_sample_reviews(reviews: list, limit: int = 3) -> list:
    samples = []
    for rev in reviews:
        text = rev.get("review_text") or ""
        if not text:
            continue
        samples.append({
            "rating": rev.get("review_rating"),
            "text":   text[:300],
            "date":   rev.get("review_datetime_utc") or rev.get("review_date"),
        })
        if len(samples) >= limit:
            break
    return samples


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main():
    place_id = os.environ.get("PLACE_ID") or (sys.argv[1] if len(sys.argv) > 1 else None)
    if not place_id:
        print("❌ Missing place_id. Pass as argv[1] or $PLACE_ID.")
        sys.exit(1)

    if not os.path.exists(DATA_PATH):
        print(f"❌ {DATA_PATH} not found. Run fetch_restaurants.py first.")
        sys.exit(1)

    with open(DATA_PATH, encoding="utf-8") as f:
        data = json.load(f)

    restaurants = data.get("restaurants", [])
    target = next((r for r in restaurants if r.get("place_id") == place_id), None)
    if not target:
        print(f"❌ place_id {place_id} not found in {DATA_PATH}")
        sys.exit(1)

    print(f"🎯 Analyzing trend for: {target.get('name')} ({place_id})")
    reviews = fetch_reviews_for(place_id)

    rating = target.get("rating") or 0
    trend_info = compute_trend(rating, reviews)
    samples = build_sample_reviews(reviews)

    # Fold trend_pain into the score, recompute tier
    rating_pain = target.get("rating_pain") or 0
    volume_pain = target.get("volume_pain") or 0
    new_score = min(100, rating_pain + volume_pain + trend_info["trend_pain"])
    new_tier = (
        "Hot Lead"    if new_score >= 70 else
        "Warm Lead"   if new_score >= 50 else
        "Nurture"     if new_score >= 30 else
        "Low Priority"
    )

    target.update({
        **trend_info,
        "trend_analyzed": True,
        "trend_analyzed_at": datetime.now(timezone.utc).isoformat(),
        "sample_reviews": samples,
        "score": new_score,
        "tier": new_tier,
    })

    # Re-sort restaurants by score (so dashboard order stays consistent)
    restaurants.sort(key=lambda x: x.get("score", 0), reverse=True)
    data["restaurants"] = restaurants

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n📈 Trend: {trend_info['trend']} (pain +{trend_info['trend_pain']})")
    print(f"   Score: {target.get('score')} → tier: {new_tier}")
    print(f"   Samples: {len(samples)} reviews with text captured")


if __name__ == "__main__":
    main()
