"""
TavoloPieno — Email digests via Resend
======================================
Sends each customer their weekly digest (or welcome email) pointing to
their private report page. Customer emails are resolved from Stripe at
send time and used in memory only — they never touch the repo.

Runs as a CLI (`python scripts/emailer.py`) at the END of a workflow,
AFTER the report pages are committed and GitHub Pages had time to
deploy, reading the outbox the monitoring step left in $RUNNER_TEMP.

Resend free tier: 100 emails/day. IMPORTANT: until a sending domain is
verified in Resend, emails only deliver to the account owner's own
address from onboarding@resend.dev — see README.
"""

import json
import os
import sys

import requests

import stripe_client

PUBLIC_BASE_URL = os.environ.get(
    "PUBLIC_BASE_URL", "https://maxlomu.github.io/tavolopieno"
)
DEFAULT_FROM = "TavoloPieno <onboarding@resend.dev>"


# ──────────────────────────────────────────────
# Outbox (runner-local, never committed)
# ──────────────────────────────────────────────

def outbox_path() -> str:
    return os.environ.get("OUTBOX_PATH") or os.path.join(
        os.environ.get("RUNNER_TEMP", "/tmp"), "outbox.json"
    )


def append_outbox(entry: dict) -> None:
    path = outbox_path()
    entries = []
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                entries = json.load(f)
        except (json.JSONDecodeError, OSError):
            entries = []
    entries.append(entry)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=1)


# ──────────────────────────────────────────────
# Sending
# ──────────────────────────────────────────────

def send(to: str, subject: str, html: str) -> bool:
    key = os.environ.get("RESEND_KEY")
    if not key:
        print("   ⚠️ RESEND_KEY missing — email not sent")
        return False
    r = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "from": os.environ.get("RESEND_FROM") or DEFAULT_FROM,
            "to": [to],
            "subject": subject,
            "html": html,
        },
        timeout=30,
    )
    if r.status_code in (200, 201):
        return True
    print(f"   ⚠️ Resend error {r.status_code}: {r.text[:300]}")
    return False


def _stars(avg) -> str:
    try:
        return f"{float(avg):.1f}★"
    except (TypeError, ValueError):
        return "—"


def build_email(entry: dict) -> tuple[str, str]:
    """Return (subject, html) for one outbox entry."""
    name = entry.get("restaurant_name") or "il tuo ristorante"
    n_new = entry.get("n_new", 0)
    report_url = f"{PUBLIC_BASE_URL}/r/{entry['token']}.html"
    welcome = entry.get("kind") == "welcome"

    if welcome:
        subject = f"Benvenuto su TavoloPieno — il report di {name} è pronto"
        lead = (
            f"Il monitoraggio di <strong>{name}</strong> è attivo. "
            "Qui sotto trovi il link alla tua pagina privata: salvala tra i preferiti, "
            "la aggiorniamo ogni settimana con le nuove recensioni e le risposte pronte da copiare."
        )
    elif entry.get("has_negative"):
        subject = f"⚠️ {name}: nuova recensione negativa — bozza di risposta pronta"
        lead = (
            f"Questa settimana <strong>{name}</strong> ha ricevuto {n_new} "
            f"nuov{'a recensione' if n_new == 1 else 'e recensioni'} "
            f"(media {_stars(entry.get('avg_new_rating'))}), di cui almeno una negativa. "
            "La risposta è già scritta: rileggila e pubblicala prima possibile — "
            "una risposta rapida e garbata recupera quasi sempre il cliente."
        )
    else:
        subject = f"TavoloPieno · {name}: {n_new} nuov{'a recensione' if n_new == 1 else 'e recensioni'} questa settimana"
        lead = (
            f"Questa settimana <strong>{name}</strong> ha ricevuto {n_new} "
            f"nuov{'a recensione' if n_new == 1 else 'e recensioni'} "
            f"(media {_stars(entry.get('avg_new_rating'))}). "
            "Le risposte sono pronte da copiare sulla tua pagina privata."
        )

    html = f"""\
<div style="font-family:Georgia,serif;max-width:560px;margin:0 auto;color:#1a1410;">
  <div style="padding:28px 24px;background:#f7f3ec;border-radius:12px;">
    <div style="font-size:22px;font-weight:bold;margin-bottom:4px;">
      Tavolo<span style="color:#c1440e;">Pieno</span>
    </div>
    <p style="font-family:Helvetica,Arial,sans-serif;font-size:15px;line-height:1.6;">{lead}</p>
    <p style="text-align:center;margin:28px 0;">
      <a href="{report_url}"
         style="font-family:Helvetica,Arial,sans-serif;background:#c1440e;color:#ffffff;text-decoration:none;
                padding:14px 28px;border-radius:10px;font-weight:bold;font-size:15px;display:inline-block;">
        Apri il tuo report privato
      </a>
    </p>
    <p style="font-family:Helvetica,Arial,sans-serif;font-size:12px;color:#6b6560;line-height:1.5;">
      Se il link non si apre subito, riprova tra un minuto: la pagina potrebbe essere ancora in aggiornamento.<br>
      Questo link è personale — non condividerlo.
    </p>
  </div>
  <p style="font-family:Helvetica,Arial,sans-serif;font-size:11px;color:#6b6560;text-align:center;margin-top:16px;">
    Ricevi questa email perché sei abbonato a TavoloPieno.
    Per disdire o gestire l'abbonamento rispondi a questa email.
  </p>
</div>"""
    return subject, html


def main() -> int:
    path = outbox_path()
    if not os.path.exists(path):
        print("📭 No outbox — nothing to send")
        return 0
    try:
        with open(path, encoding="utf-8") as f:
            entries = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"❌ Cannot read outbox {path}: {e}")
        return 1
    if not entries:
        print("📭 Outbox empty — nothing to send")
        return 0

    emails = {}
    if stripe_client.stripe_enabled():
        try:
            emails = stripe_client.list_active_subscriptions()
        except Exception as e:
            print(f"⚠️ Stripe lookup failed, cannot resolve recipients: {e}")
    else:
        print("⚠️ STRIPE_KEY missing — recipients cannot be resolved")

    sent = 0
    for entry in entries:
        cus_id = entry.get("stripe_customer_id") or ""
        to = emails.get(cus_id) or entry.get("test_email") or ""
        label = entry.get("restaurant_name") or entry.get("token")
        if not to:
            print(f"   ⚠️ No email for {label} ({cus_id or 'no stripe id'}) — skipped")
            continue
        subject, html = build_email(entry)
        if send(to, subject, html):
            sent += 1
            print(f"   📧 Sent to customer of {label}")
    print(f"\n📮 {sent}/{len(entries)} digest(s) sent")
    return 0  # one bad address never fails the job


if __name__ == "__main__":
    sys.exit(main())
