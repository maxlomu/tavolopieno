"""
TavoloPieno — Customer activation / deactivation (concierge step)
=================================================================
Run via the "Attiva cliente" workflow after someone subscribes:

  CUSTOMER_REF  Stripe customer id (cus_…) or the email used at checkout
  PLACE_ID      the restaurant's Google place_id (find it in /leads.html
                or via Google Maps)
  ACTION        "activate" (default) or "deactivate"

Activation: verifies the Stripe customer, generates an unguessable
token, adds the customer to data/customers.json (NO email — PII stays
in Stripe), runs the first monitoring cycle immediately so the report
page exists, and queues the welcome email.

Deactivation: flips status to "cancelled". State and the last report
are kept; monitoring and emails stop.
"""

import os
import secrets
import sys

import monitor_customers as mon
import stripe_client


def find_by_place(registry: dict, place_id: str) -> dict | None:
    for c in registry["customers"]:
        if c.get("place_id") == place_id:
            return c
    return None


def activate(registry: dict, customer_ref: str, place_id: str) -> int:
    existing = find_by_place(registry, place_id)
    if existing and existing.get("status") == "active":
        print(f"✅ Already active: {existing.get('restaurant_name') or place_id} "
              f"(token {existing['token']}) — nothing to do")
        return 0

    stripe_customer_id = ""
    if stripe_client.stripe_enabled() and customer_ref:
        found = stripe_client.find_customer(customer_ref)
        if found:
            stripe_customer_id = found["id"]
            print(f"💳 Stripe customer: {stripe_customer_id}")
            if not stripe_client.has_active_subscription(stripe_customer_id):
                print("⚠️ No ACTIVE subscription for this customer yet — "
                      "activating anyway (maybe payment is still settling). "
                      "The weekly run will auto-deactivate if it never becomes active.")
        else:
            print(f"⚠️ Stripe customer {customer_ref!r} not found — activating without "
                  "a Stripe link. Emails can NOT be delivered until you re-activate "
                  "with a valid Stripe customer id or email.")
    else:
        print("⚠️ STRIPE_KEY or CUSTOMER_REF missing — activating without a Stripe link "
              "(test mode: emails cannot be resolved).")

    if existing:  # was cancelled → reactivate, keep token/state/history
        existing["status"] = "active"
        existing["deactivated_at"] = None
        if stripe_customer_id:
            existing["stripe_customer_id"] = stripe_customer_id
        customer = existing
        print("🔄 Reactivating previously cancelled customer (history kept)")
    else:
        customer = {
            "token": secrets.token_urlsafe(16),
            "place_id": place_id,
            "restaurant_name": "",
            "stripe_customer_id": stripe_customer_id,
            "plan": "base",
            "status": "active",
            "activated_at": mon.now_iso(),
            "deactivated_at": None,
        }
        registry["customers"].append(customer)

    # First cycle right now, so the welcome email links to a live report
    mon.process_customer(customer, force_email=True)
    mon.save_registry(registry)

    print(f"\n🎉 Activated: {customer.get('restaurant_name') or place_id}")
    print(f"   Private report: {os.environ.get('PUBLIC_BASE_URL', 'https://maxlomu.github.io/tavolopieno')}/r/{customer['token']}.html")
    return 0


def deactivate(registry: dict, customer_ref: str, place_id: str) -> int:
    target = None
    if place_id:
        target = find_by_place(registry, place_id)
    if not target and customer_ref:
        target = next(
            (c for c in registry["customers"]
             if customer_ref in (c.get("stripe_customer_id"), c.get("token"))),
            None,
        )
    if not target:
        print(f"❌ No customer matches place_id={place_id!r} / ref={customer_ref!r}")
        return 1
    if target.get("status") != "active":
        print(f"✅ {target.get('restaurant_name') or target['place_id']} is already inactive")
        return 0
    target["status"] = "cancelled"
    target["deactivated_at"] = mon.now_iso()
    mon.save_registry(registry)
    print(f"🚫 Deactivated {target.get('restaurant_name') or target['place_id']} "
          "(report kept, monitoring and emails stopped)")
    return 0


def main() -> int:
    customer_ref = (os.environ.get("CUSTOMER_REF") or "").strip()
    place_id = (os.environ.get("PLACE_ID") or "").strip()
    action = (os.environ.get("ACTION") or "activate").strip().lower()

    registry = mon.load_registry()

    if action == "deactivate":
        return deactivate(registry, customer_ref, place_id)
    if not place_id:
        print("❌ PLACE_ID is required to activate a customer")
        return 1
    return activate(registry, customer_ref, place_id)


if __name__ == "__main__":
    sys.exit(main())
