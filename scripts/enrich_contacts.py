"""
TavoloPieno — Contact enrichment
================================
Reads docs/data.json, takes the first N restaurants that have a
website, and asks Outscraper's /contacts-and-leads endpoint for
emails, phones, and contact names/roles scraped from those sites.

Writes back into each restaurant:
  primary_email         — best email to use (named contact preferred)
  primary_contact_name  — person's name (if any was found)
  primary_contact_title — their role/title (if any)
  all_emails            — list of all emails scraped
  contacts              — full list of {name, title, email, phone}
"""

import ast
import json
import os
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

OUTSCRAPER_KEY = os.environ.get("OUTSCRAPER_KEY")
if not OUTSCRAPER_KEY:
    print("❌ Missing OUTSCRAPER_KEY environment variable")
    sys.exit(1)

BASE = "https://api.outscraper.cloud"
HEADERS = {"X-API-KEY": OUTSCRAPER_KEY}

DATA_PATH = "docs/data.json"
MAX_RESTAURANTS = 10   # cost cap while testing; set to None for all
CONTACTS_PER_COMPANY = 3


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
# Parsing helpers
# ──────────────────────────────────────────────

def _coerce_list(raw):
    """Outscraper sometimes returns nested lists as Python-repr strings."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str) and raw.strip().startswith("["):
        try:
            parsed = ast.literal_eval(raw)
            if isinstance(parsed, list):
                return parsed
        except (ValueError, SyntaxError):
            pass
    return []


def normalize_domain(url: str) -> str:
    """Strip scheme/path so Outscraper gets a clean domain."""
    if not url:
        return ""
    parsed = urlparse(url if "://" in url else f"http://{url}")
    host = parsed.netloc or parsed.path
    return host.strip("/").lower()


def extract_contact_fields(entry: dict) -> dict:
    """
    Pull the interesting fields out of an Outscraper contacts-and-leads
    entry. Tolerant of field-name variation because the endpoint's
    schema isn't publicly documented in detail.
    """
    # Flat email_1..email_N shape
    all_emails = []
    for k, v in entry.items():
        if k.startswith("email_") and isinstance(v, str) and "@" in v:
            all_emails.append(v.strip())
    # Also check a unified `emails` list
    emails_field = entry.get("emails")
    if isinstance(emails_field, list):
        for e in emails_field:
            if isinstance(e, str) and "@" in e:
                all_emails.append(e.strip())
            elif isinstance(e, dict):
                val = e.get("value") or e.get("email")
                if val:
                    all_emails.append(val.strip())

    # Deduplicate, preserve order
    seen = set()
    all_emails = [e for e in all_emails if not (e in seen or seen.add(e))]

    # Contact list with name/title (field name varies)
    contacts_raw = (
        entry.get("contacts")
        or entry.get("persons")
        or entry.get("people")
        or []
    )
    contacts_raw = _coerce_list(contacts_raw)

    contacts = []
    for c in contacts_raw:
        if not isinstance(c, dict):
            continue
        name = c.get("name") or c.get("full_name") or c.get("person_name")
        title = c.get("title") or c.get("role") or c.get("position")
        # Per-contact emails
        c_email = None
        if isinstance(c.get("emails"), list) and c["emails"]:
            first = c["emails"][0]
            c_email = first if isinstance(first, str) else first.get("value") or first.get("email")
        c_email = c_email or c.get("email")
        contacts.append({
            "name": name,
            "title": title,
            "email": c_email,
        })

    # Pick a primary: prefer a named contact with email, else first generic email
    primary_email = None
    primary_name = None
    primary_title = None
    for c in contacts:
        if c.get("name") and c.get("email"):
            primary_email = c["email"]
            primary_name = c["name"]
            primary_title = c.get("title")
            break
    if not primary_email and all_emails:
        primary_email = all_emails[0]

    return {
        "primary_email": primary_email,
        "primary_contact_name": primary_name,
        "primary_contact_title": primary_title,
        "all_emails": all_emails,
        "contacts": contacts,
    }


# ──────────────────────────────────────────────
# Outscraper call
# ──────────────────────────────────────────────

def fetch_contacts(domains: list) -> dict:
    """
    Returns {domain: contact_info}. One Outscraper task covers all domains.
    """
    print(f"📧 Fetching contacts for {len(domains)} domains...")
    params = {
        "query": domains,
        "contacts_per_company": CONTACTS_PER_COMPANY,
        "emails_per_contact": 1,
        "general_emails": "true",   # include info@, prenotazioni@ as fallback
        "async": "true",
    }
    data = call_async("contacts-and-leads", params)

    # ── One-time diagnostic dump so we can confirm the shape ──
    print("\n──── RAW RESPONSE DIAGNOSTICS ────")
    print(f"type(data)={type(data).__name__}  len={len(data) if hasattr(data,'__len__') else 'n/a'}")
    for i in range(min(2, len(data))):
        e = data[i]
        print(f"\n  data[{i}]: type={type(e).__name__}")
        if isinstance(e, dict):
            print(f"    keys={list(e.keys())}")
            print(f"    sample={json.dumps({k: str(v)[:100] for k,v in e.items()}, ensure_ascii=False)[:1500]}")
        elif isinstance(e, list) and e:
            print(f"    len={len(e)}, first keys={list(e[0].keys()) if isinstance(e[0], dict) else 'n/a'}")
    print("──── END DIAGNOSTICS ────\n")

    result = {}
    for i, entry in enumerate(data):
        if i >= len(domains):
            break
        # Entry may be a 1-element list wrapping a dict, or a dict directly.
        if isinstance(entry, list) and entry and isinstance(entry[0], dict):
            record = entry[0]
        elif isinstance(entry, dict):
            record = entry
        else:
            continue
        result[domains[i]] = extract_contact_fields(record)

    hits = sum(1 for v in result.values() if v.get("all_emails"))
    print(f"   ✅ {hits}/{len(domains)} domains returned at least one email")
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

    # Pick the first N restaurants (by existing order in data.json, which is
    # sorted by pain score descending) that have a usable website.
    pool = restaurants if MAX_RESTAURANTS is None else restaurants[:MAX_RESTAURANTS]
    targets = []
    for r in pool:
        domain = normalize_domain(r.get("website") or "")
        if domain:
            targets.append((r["place_id"], domain, r["name"]))

    skipped = len(pool) - len(targets)
    print(f"📂 Loaded {len(restaurants)} restaurants, targeting first {len(pool)}")
    print(f"   → {len(targets)} have a website, {skipped} don't (skipping those)")

    if not targets:
        print("❌ None of the targeted restaurants have a website — nothing to enrich.")
        sys.exit(0)

    domains = [t[1] for t in targets]
    contacts_by_domain = fetch_contacts(domains)

    # Map back to place_id → contact info (domains can repeat, so use the
    # domain lookup rather than positional mapping)
    enriched = 0
    for pid, domain, name in targets:
        info = contacts_by_domain.get(domain)
        if not info:
            continue
        # Find the restaurant in data.json and merge in the contact fields
        for r in restaurants:
            if r.get("place_id") == pid:
                r.update(info)
                if info.get("all_emails"):
                    enriched += 1
                break

    data["contacts_enriched_at"] = datetime.now(timezone.utc).isoformat()

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n🎯 Enriched {enriched}/{len(targets)} restaurants with at least one email")


if __name__ == "__main__":
    main()
