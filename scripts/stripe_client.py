"""
TavoloPieno — Stripe client
===========================
Stripe IS the customer database. Emails and payment details live only
there; the repo stores just place_id + an anonymous token per customer.

Uses the plain REST API with `requests` (no stripe SDK). The key in
STRIPE_KEY should be a *restricted* key with read access to Customers
and Subscriptions — that is all these helpers need.
"""

import os

import requests

BASE = "https://api.stripe.com/v1"


def stripe_enabled() -> bool:
    return bool(os.environ.get("STRIPE_KEY"))


def _get(path: str, params: dict | None = None) -> dict:
    key = os.environ.get("STRIPE_KEY")
    if not key:
        raise RuntimeError("Missing STRIPE_KEY environment variable")
    r = requests.get(f"{BASE}/{path}", params=params or {}, auth=(key, ""), timeout=30)
    r.raise_for_status()
    return r.json()


def list_active_subscriptions() -> dict:
    """
    Return {stripe_customer_id: email} for every active subscription.
    Follows pagination; `expand[]=data.customer` gives us the email in
    the same call, in memory only — it is never written to disk.
    """
    out = {}
    params = {"status": "active", "limit": 100, "expand[]": "data.customer"}
    while True:
        page = _get("subscriptions", params)
        for sub in page.get("data", []):
            cust = sub.get("customer")
            if isinstance(cust, dict):
                out[cust.get("id")] = cust.get("email") or ""
            elif isinstance(cust, str):
                out[cust] = ""
        if not page.get("has_more") or not page.get("data"):
            return out
        params["starting_after"] = page["data"][-1]["id"]


def find_customer(ref: str) -> dict | None:
    """
    Resolve `ref` (a cus_… id or an email address) to
    {"id": ..., "email": ...}, or None if not found.
    """
    ref = (ref or "").strip()
    if not ref:
        return None
    try:
        if ref.startswith("cus_"):
            c = _get(f"customers/{ref}")
            return {"id": c["id"], "email": c.get("email") or ""}
        page = _get("customers", {"email": ref, "limit": 1})
        data = page.get("data", [])
        if data:
            return {"id": data[0]["id"], "email": data[0].get("email") or ""}
    except requests.HTTPError as e:
        print(f"   ⚠️ Stripe lookup failed for {ref!r}: {e}")
    return None


def has_active_subscription(customer_id: str) -> bool:
    page = _get("subscriptions", {"customer": customer_id, "status": "active", "limit": 1})
    return bool(page.get("data"))
