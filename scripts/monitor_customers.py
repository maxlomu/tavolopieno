"""
TavoloPieno — Weekly customer monitoring engine
===============================================
For every active paying customer:
  1. fetch their Google profile snapshot + newest reviews (one
     Outscraper call, see outscraper_client.py)
  2. diff against the reviews we have already seen
  3. draft an Italian owner-reply for each new review (Claude)
  4. update the customer's state file and regenerate their private
     report page docs/r/<token>.html
  5. queue an email digest in the runner-local outbox (sent later by
     emailer.py, after the reports are committed and Pages deployed)

Also validates subscriptions against Stripe: customers whose
subscription is no longer active are flipped to "cancelled" and
skipped from then on. If STRIPE_KEY is absent (local testing) the
check is skipped gracefully.

Usage:
  python scripts/monitor_customers.py            # all active customers
  python scripts/monitor_customers.py --token X  # just one
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

import emailer
import llm
import outscraper_client
import report
import stripe_client

REGISTRY_PATH = "data/customers.json"
STATE_DIR = "data/state"
REPORT_DIR = "docs/r"

SEEN_IDS_CAP = 300     # most recent review ids remembered per customer
STORED_REVIEWS_CAP = 60


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ──────────────────────────────────────────────
# Registry / state I/O
# ──────────────────────────────────────────────

def load_registry() -> dict:
    if not os.path.exists(REGISTRY_PATH):
        return {"customers": []}
    with open(REGISTRY_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_registry(registry: dict) -> None:
    os.makedirs(os.path.dirname(REGISTRY_PATH), exist_ok=True)
    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)


def state_path(token: str) -> str:
    return os.path.join(STATE_DIR, f"{token}.json")


def load_state(customer: dict) -> dict:
    path = state_path(customer["token"])
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {
        "token": customer["token"],
        "place_id": customer["place_id"],
        "last_run_at": None,
        "seen_review_ids": [],
        "snapshots": [],
        "reviews": [],
    }


def save_state(state: dict) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(state_path(state["token"]), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ──────────────────────────────────────────────
# Normalization
# ──────────────────────────────────────────────

def review_key(rev: dict) -> str:
    rid = rev.get("review_id")
    if rid:
        return str(rid)
    raw = f"{rev.get('author_title', '')}|{rev.get('review_datetime_utc') or rev.get('review_date', '')}|{(rev.get('review_text') or '')[:80]}"
    return "h_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def normalize_reviews(place: dict) -> list:
    out = []
    for rev in place.get("reviews_data", []) or []:
        out.append({
            "review_id": review_key(rev),
            "author": rev.get("author_title") or "",
            "rating": rev.get("review_rating"),
            "text": (rev.get("review_text") or "")[:1500],
            "date": rev.get("review_datetime_utc") or rev.get("review_date") or "",
        })
    return out


def snapshot_from(place: dict) -> dict:
    return {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "rating": place.get("rating"),
        "review_count": place.get("reviews"),
        "photos_count": place.get("photos_count"),
        "has_website": bool(place.get("site") or place.get("website")),
        "has_phone": bool(place.get("phone")),
        "has_hours": bool(place.get("working_hours")),
    }


# ──────────────────────────────────────────────
# Per-customer cycle
# ──────────────────────────────────────────────

def process_customer(customer: dict, force_email: bool = False) -> None:
    """One full monitoring cycle for one customer. Raises on failure."""
    name = customer.get("restaurant_name") or customer["place_id"]
    print(f"\n🍽️ {name}")

    place = outscraper_client.fetch_profile(customer["place_id"])
    if not place:
        raise RuntimeError(f"Outscraper returned no place for {customer['place_id']}")

    if place.get("name"):
        customer["restaurant_name"] = place["name"]

    state = load_state(customer)
    reviews = normalize_reviews(place)
    seen = set(state.get("seen_review_ids", []))
    new = [r for r in reviews if r["review_id"] not in seen]
    print(f"   💬 {len(reviews)} reviews fetched, {len(new)} new")

    drafts = llm.draft_replies(customer.get("restaurant_name") or name, new) if new else {}
    for rev in new:
        rev["draft_reply"] = drafts.get(rev["review_id"], "")
        rev["first_seen"] = now_iso()

    # newest first, capped
    state["reviews"] = (new + state.get("reviews", []))[:STORED_REVIEWS_CAP]
    state["seen_review_ids"] = (
        [r["review_id"] for r in new] + state.get("seen_review_ids", [])
    )[:SEEN_IDS_CAP]

    snap = snapshot_from(place)
    snapshots = state.get("snapshots", [])
    if snapshots and snapshots[-1].get("date") == snap["date"]:
        snapshots[-1] = snap  # re-run on the same day: replace, don't duplicate
    else:
        snapshots.append(snap)
    state["snapshots"] = snapshots
    state["last_run_at"] = now_iso()
    save_state(state)

    os.makedirs(REPORT_DIR, exist_ok=True)
    report_path = os.path.join(REPORT_DIR, f"{customer['token']}.html")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report.render_report(customer, state))
    print(f"   📄 Report → {report_path}")

    if new or force_email:
        ratings = [r["rating"] for r in new if isinstance(r.get("rating"), (int, float))]
        emailer.append_outbox({
            "kind": "welcome" if force_email else "digest",
            "stripe_customer_id": customer.get("stripe_customer_id") or "",
            "token": customer["token"],
            "restaurant_name": customer.get("restaurant_name") or "",
            "n_new": len(new),
            "avg_new_rating": round(sum(ratings) / len(ratings), 1) if ratings else None,
            "has_negative": any(r <= 2 for r in ratings),
        })
        print("   📬 Digest queued")
    else:
        print("   💤 Nothing new — no email this week")


# ──────────────────────────────────────────────
# Stripe subscription sync
# ──────────────────────────────────────────────

def sync_subscriptions(registry: dict) -> None:
    if not stripe_client.stripe_enabled():
        print("⚠️ STRIPE_KEY missing — skipping subscription check (test mode)")
        return
    try:
        active = stripe_client.list_active_subscriptions()
    except Exception as e:
        print(f"⚠️ Stripe check failed ({e}) — keeping current statuses")
        return
    for cust in registry["customers"]:
        cus_id = cust.get("stripe_customer_id")
        if cust.get("status") == "active" and cus_id and cus_id not in active:
            cust["status"] = "cancelled"
            cust["deactivated_at"] = now_iso()
            print(f"🚫 Subscription ended → deactivated {cust.get('restaurant_name') or cust['place_id']}")


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", default=os.environ.get("ONLY_TOKEN") or None,
                        help="process only the customer with this token")
    args = parser.parse_args()

    registry = load_registry()
    sync_subscriptions(registry)

    targets = [
        c for c in registry["customers"]
        if c.get("status") == "active" and (not args.token or c["token"] == args.token)
    ]
    if not targets:
        save_registry(registry)
        print("📭 No active customers to monitor")
        return 0

    failures = 0
    for cust in targets:
        try:
            process_customer(cust)
        except Exception as e:
            failures += 1
            print(f"   ❌ {cust.get('restaurant_name') or cust['place_id']}: {e}")

    save_registry(registry)
    print(f"\n🎯 {len(targets) - failures}/{len(targets)} customers processed")
    # partial failures shouldn't kill the run (and the commit of the others)
    return 1 if failures == len(targets) else 0


if __name__ == "__main__":
    sys.exit(main())
