"""
TavoloPieno — Outscraper client (SaaS side)
===========================================
Shared Outscraper helpers for the customer-monitoring scripts.

Deliberately a *copy* of the async-task helpers that live inside
fetch_restaurants.py / analyze_trend.py: the lead-gen scripts keep
their own embedded copies on purpose, so nothing in the working
pipeline changes when this module evolves.

One profile fetch uses maps/reviews-v3 only: its response contains the
full place record (rating, review count, site, phone, hours, photos)
PLUS the newest reviews, so a single call covers both the weekly
snapshot and the review diff. Cost ≈ $3/1000 reviews → with
REVIEWS_LIMIT=30 that is about $0.09 per customer per run.
"""

import os
import time

import requests

BASE = "https://api.outscraper.cloud"

# Hard cost cap: never pull more than this many reviews per customer per run.
REVIEWS_LIMIT = 30


def _headers() -> dict:
    key = os.environ.get("OUTSCRAPER_KEY")
    if not key:
        raise RuntimeError("Missing OUTSCRAPER_KEY environment variable")
    return {"X-API-KEY": key}


def wait_for_task(url: str, max_wait: int = 300) -> list:
    print(f"   ⏳ Waiting for task: {url}")
    start = time.time()
    while time.time() - start < max_wait:
        r = requests.get(url, headers=_headers(), timeout=30)
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
    r = requests.get(f"{BASE}/{endpoint}", headers=_headers(), params=params, timeout=60)
    r.raise_for_status()
    body = r.json()
    if "results_location" in body:
        return wait_for_task(body["results_location"])
    return body.get("data", [])


def fetch_profile(place_id: str, reviews_limit: int = REVIEWS_LIMIT) -> dict:
    """
    Fetch the place record + its newest reviews in one reviews-v3 call.
    Returns the place dict (with a "reviews_data" list), or {} if the
    place could not be resolved.
    """
    params = {
        "query": place_id,
        "reviewsLimit": min(reviews_limit, REVIEWS_LIMIT),
        "language": "it",
        "sort": "newest",
        "async": "true",
    }
    data = call_async("maps/reviews-v3", params)
    # data may be [place_dict] or [[place_dict]]
    if data and isinstance(data[0], list) and data[0]:
        place = data[0][0] if isinstance(data[0][0], dict) else {}
    elif data and isinstance(data[0], dict):
        place = data[0]
    else:
        place = {}
    return place or {}
