"""
TavoloPieno — AI reply drafting
===============================
Drafts an Italian owner-reply for each new Google review, in one
batched Claude call per customer per run. Plain `requests`, no SDK.

Cost note: claude-haiku-4-5 is ~$1/$5 per million tokens; a full
week of drafts for one restaurant costs well under €0.01.
"""

import json
import os

import requests

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-haiku-4-5"

# Guardrail: even if a customer somehow gets 30 new reviews in a week,
# never draft more than this many replies in one run.
MAX_DRAFTS_PER_RUN = 15

SYSTEM_PROMPT = """Sei il titolare di un ristorante italiano che risponde personalmente alle recensioni Google del proprio locale. Scrivi SOLO in italiano.

Tono: caloroso, professionale, concreto — come un ristoratore esperto che ci tiene davvero. Mai servile, mai burocratico.

Regole ferree:
- 40–90 parole per risposta.
- Recensioni positive (4–5 stelle): ringrazia citando UN dettaglio specifico che il cliente ha menzionato (un piatto, il servizio, l'atmosfera). Invitalo a tornare.
- Recensioni tiepide o negative (1–3 stelle): ringrazia per il feedback, scusati per l'esperienza SENZA ammettere colpe specifiche non verificabili e SENZA inventare spiegazioni o fatti. Non promettere MAI rimborsi, sconti od omaggi. Invita a ricontattare il locale di persona o al telefono per chiarire. Non discutere, non giustificarti a lungo, non essere sarcastico.
- Se la recensione non ha testo (solo stelle), scrivi comunque una risposta breve e adeguata al voto.
- Non firmare con nomi di persona. Puoi chiudere con il nome del ristorante.
- Non usare emoji. Non usare inglese.

Rispondi ESCLUSIVAMENTE con JSON valido, nessun altro testo, in questo formato:
{"replies": [{"review_id": "...", "reply": "..."}]}"""


def _parse_json(text: str) -> dict | None:
    text = text.strip()
    if text.startswith("```"):
        # strip a ```json … ``` fence
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def draft_replies(restaurant_name: str, reviews: list) -> dict:
    """
    reviews: [{review_id, rating, text, author}, ...] (new reviews only).
    Returns {review_id: reply}. Empty dict if the key is missing or the
    call fails — callers degrade gracefully ("bozza non disponibile").
    """
    api_key = os.environ.get("ANTHROPIC_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("   ⚠️ ANTHROPIC_KEY missing — skipping reply drafts")
        return {}
    if not reviews:
        return {}

    batch = reviews[:MAX_DRAFTS_PER_RUN]
    items = []
    for rev in batch:
        items.append({
            "review_id": rev["review_id"],
            "stelle": rev.get("rating"),
            "autore": rev.get("author") or "un cliente",
            "testo": rev.get("text") or "(nessun testo, solo la valutazione in stelle)",
        })
    user_msg = (
        f'Ristorante: "{restaurant_name}"\n'
        f"Scrivi una risposta del titolare per ognuna di queste {len(items)} recensioni:\n"
        + json.dumps(items, ensure_ascii=False, indent=1)
    )

    payload = {
        "model": MODEL,
        "max_tokens": min(4000, 400 + 250 * len(items)),
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_msg}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    for attempt in (1, 2):
        try:
            r = requests.post(API_URL, headers=headers, json=payload, timeout=120)
            r.raise_for_status()
            text = "".join(
                block.get("text", "")
                for block in r.json().get("content", [])
                if block.get("type") == "text"
            )
            parsed = _parse_json(text)
            if parsed and isinstance(parsed.get("replies"), list):
                out = {
                    item["review_id"]: item["reply"].strip()
                    for item in parsed["replies"]
                    if item.get("review_id") and item.get("reply")
                }
                print(f"   ✍️ Drafted {len(out)}/{len(items)} replies")
                return out
            print(f"   ⚠️ Unparseable LLM output (attempt {attempt})")
        except requests.RequestException as e:
            print(f"   ⚠️ Claude API error (attempt {attempt}): {e}")
    return {}
