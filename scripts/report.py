"""
TavoloPieno — Private customer report page
==========================================
Renders one customer's report as a single self-contained HTML file
(docs/r/<token>.html). All data is INLINED into the page — no sibling
JSON fetches — so the report works anywhere GitHub Pages serves it.

Same visual system as the rest of the site (Fraunces/Inter, cream &
terracotta palette). Vanilla HTML/CSS/JS, no build step.
"""

import html
from datetime import datetime, timezone

MIN_PHOTOS_OK = 10  # below this, the GBP checklist flags "poche foto"
MAX_REVIEWS_SHOWN = 20


def _esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def _stars(rating) -> str:
    try:
        n = int(round(float(rating)))
    except (TypeError, ValueError):
        return "—"
    n = max(0, min(5, n))
    return "★" * n + "☆" * (5 - n)


def _fmt_date(iso: str) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).strftime("%d/%m/%Y")
    except ValueError:
        return str(iso)[:10]


def _trend_svg(snapshots: list) -> str:
    """Inline SVG polyline of the rating over time (1–5 scale)."""
    points = [
        (s.get("date", ""), s["rating"])
        for s in snapshots
        if isinstance(s.get("rating"), (int, float)) and s["rating"] > 0
    ]
    if len(points) < 2:
        return (
            '<div class="chart-empty">Il grafico dell\'andamento apparirà '
            "dalla seconda settimana di monitoraggio.</div>"
        )
    w, h, pad = 640, 180, 28
    n = len(points)
    ratings = [r for _, r in points]
    # Zoom the y-axis to the data (±0.3★, min span 0.6★, clamped to 1–5)
    # so a 4.4 → 4.1 slide is clearly visible instead of a flat line.
    lo = max(1.0, min(ratings) - 0.3)
    hi = min(5.0, max(ratings) + 0.3)
    if hi - lo < 0.6:
        mid = (hi + lo) / 2
        lo, hi = max(1.0, mid - 0.3), min(5.0, mid + 0.3)

    def y_of(r: float) -> float:
        return pad + (hi - r) * (h - 2 * pad) / (hi - lo)

    xs = [pad + 14 + i * (w - 2 * pad - 14) / (n - 1) for i in range(n)]
    ys = [y_of(r) for r in ratings]
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    dots = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="#c1440e">'
        f"<title>{_esc(d)}: {r}★</title></circle>"
        for (d, r), x, y in zip(points, xs, ys)
    )
    ticks = [lo + i * (hi - lo) / 4 for i in range(5)]
    gridlines = "".join(
        f'<line x1="{pad + 14}" y1="{y_of(g):.1f}" x2="{w - pad}" y2="{y_of(g):.1f}" '
        f'stroke="#e6dfd3" stroke-width="1"/>'
        f'<text x="{pad + 8}" y="{y_of(g) + 4:.1f}" '
        f'text-anchor="end" font-size="11" fill="#6b6560">{g:.1f}</text>'
        for g in ticks
    )
    first_label = _esc(_fmt_date(points[0][0]))
    last_label = _esc(_fmt_date(points[-1][0]))
    return f"""\
<svg viewBox="0 0 {w} {h + 20}" role="img" aria-label="Andamento del voto" style="width:100%;height:auto;">
  {gridlines}
  <polyline points="{poly}" fill="none" stroke="#c1440e" stroke-width="2.5" stroke-linejoin="round"/>
  {dots}
  <text x="{pad}" y="{h + 12}" font-size="11" fill="#6b6560">{first_label}</text>
  <text x="{w - pad}" y="{h + 12}" text-anchor="end" font-size="11" fill="#6b6560">{last_label}</text>
</svg>"""


def _checklist(snap: dict) -> str:
    photos = snap.get("photos_count")
    items = [
        (snap.get("has_website"), "Sito web collegato al profilo",
         "Aggiungi il sito: i clienti (e Google) si fidano di più."),
        (snap.get("has_phone"), "Numero di telefono presente",
         "Aggiungi il telefono: molte prenotazioni arrivano da lì."),
        (snap.get("has_hours"), "Orari di apertura completi",
         "Completa gli orari: senza, Google ti penalizza nelle ricerche."),
        (photos is None or photos >= MIN_PHOTOS_OK,
         f"Foto sul profilo ({'n.d.' if photos is None else photos})",
         f"Carica più foto (almeno {MIN_PHOTOS_OK}): i locali con foto ricevono più visite."),
    ]
    rows = []
    for ok, label, hint in items:
        icon = "✅" if ok else "❌"
        hint_html = "" if ok else f'<div class="gbp-hint">{_esc(hint)}</div>'
        rows.append(
            f'<div class="gbp-item"><span class="gbp-icon">{icon}</span>'
            f"<div><div>{_esc(label)}</div>{hint_html}</div></div>"
        )
    return "".join(rows)


def _review_cards(reviews: list, place_id: str) -> str:
    google_url = f"https://search.google.com/local/reviews?placeid={_esc(place_id)}"
    if not reviews:
        return '<div class="chart-empty">Nessuna recensione registrata finora.</div>'
    cards = []
    for i, rev in enumerate(reviews[:MAX_REVIEWS_SHOWN]):
        rating = rev.get("rating")
        neg = isinstance(rating, (int, float)) and rating <= 2
        draft = (rev.get("draft_reply") or "").strip()
        if draft:
            reply_block = f"""\
      <div class="reply">
        <div class="reply-label">La tua risposta, pronta da copiare</div>
        <textarea readonly id="draft-{i}" rows="4">{_esc(draft)}</textarea>
        <div class="reply-actions">
          <button class="copy-btn" data-target="draft-{i}">📋 Copia risposta</button>
          <a class="open-google" href="{google_url}" target="_blank" rel="noopener">Apri le recensioni su Google ↗</a>
        </div>
      </div>"""
        else:
            reply_block = '<div class="reply"><div class="reply-label">Bozza non disponibile per questa recensione.</div></div>'
        text = (rev.get("text") or "").strip()
        text_html = f'<p class="rev-text">{_esc(text)}</p>' if text else '<p class="rev-text muted">(solo valutazione, nessun testo)</p>'
        cards.append(f"""\
    <div class="review{' negative' if neg else ''}">
      <div class="rev-head">
        <span class="rev-stars">{_stars(rating)}</span>
        <span class="rev-author">{_esc(rev.get('author') or 'Cliente Google')}</span>
        <span class="rev-date">{_esc(_fmt_date(rev.get('date')))}</span>
        {'<span class="rev-flag">da gestire</span>' if neg else ''}
      </div>
      {text_html}
{reply_block}
    </div>""")
    return "\n".join(cards)


def render_report(customer: dict, state: dict) -> str:
    name = customer.get("restaurant_name") or "Il tuo ristorante"
    snapshots = state.get("snapshots", [])
    snap = snapshots[-1] if snapshots else {}
    reviews = state.get("reviews", [])
    rating = snap.get("rating")
    review_count = snap.get("review_count")
    n_drafts = sum(1 for r in reviews if (r.get("draft_reply") or "").strip())
    updated = _fmt_date(state.get("last_run_at")) or _fmt_date(
        datetime.now(timezone.utc).isoformat()
    )

    return f"""\
<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex, nofollow">
<title>{_esc(name)} — Report TavoloPieno</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600;9..144,800&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root {{
    --cream:#f7f3ec; --ink:#1a1410; --ink-soft:#6b6560; --accent:#c1440e;
    --accent-soft:#fde8d8; --sage:#7a8b6f; --sage-soft:#e6ece2;
    --border:#e6dfd3; --card:#ffffff;
  }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ font-family:'Inter',system-ui,sans-serif; background:var(--cream); color:var(--ink); line-height:1.55; }}
  .wrap {{ max-width:780px; margin:0 auto; padding:36px 20px 70px; }}
  header {{ padding-bottom:24px; border-bottom:1px solid var(--border); margin-bottom:26px; }}
  .brand {{ font-family:'Fraunces',serif; font-weight:800; font-size:20px; }}
  .brand span {{ color:var(--accent); }}
  h1 {{ font-family:'Fraunces',serif; font-weight:800; font-size:clamp(26px,5vw,38px); margin-top:10px; letter-spacing:-0.02em; }}
  .sub {{ color:var(--ink-soft); font-size:14px; margin-top:6px; }}
  h2 {{ font-family:'Fraunces',serif; font-weight:600; font-size:21px; margin:34px 0 14px; }}
  .stats {{ display:grid; grid-template-columns:repeat(3,1fr); gap:12px; }}
  .stat {{ background:var(--card); border:1px solid var(--border); border-radius:12px; padding:16px 18px; }}
  .stat .label {{ font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:0.09em; color:var(--ink-soft); margin-bottom:6px; }}
  .stat .val {{ font-family:'Fraunces',serif; font-size:30px; font-weight:800; line-height:1; }}
  .stat .val small {{ font-size:14px; color:var(--ink-soft); font-weight:400; }}
  .panel {{ background:var(--card); border:1px solid var(--border); border-radius:14px; padding:20px 22px; }}
  .chart-empty {{ color:var(--ink-soft); font-size:14px; padding:18px 4px; }}
  .gbp-item {{ display:flex; gap:12px; padding:10px 0; border-bottom:1px dashed var(--border); font-size:14.5px; }}
  .gbp-item:last-child {{ border-bottom:none; }}
  .gbp-icon {{ flex-shrink:0; }}
  .gbp-hint {{ color:var(--accent); font-size:12.5px; margin-top:2px; }}
  .review {{ background:var(--card); border:1px solid var(--border); border-radius:14px; padding:18px 20px; margin-bottom:14px; }}
  .review.negative {{ border-color:var(--accent); box-shadow:0 3px 14px rgba(193,68,14,0.07); }}
  .rev-head {{ display:flex; gap:10px; align-items:baseline; flex-wrap:wrap; margin-bottom:8px; }}
  .rev-stars {{ color:var(--accent); font-size:15px; letter-spacing:2px; }}
  .rev-author {{ font-weight:600; font-size:14px; }}
  .rev-date {{ color:var(--ink-soft); font-size:12.5px; }}
  .rev-flag {{ background:var(--accent-soft); color:var(--accent); font-size:10.5px; font-weight:700; text-transform:uppercase; letter-spacing:0.07em; padding:2px 9px; border-radius:99px; }}
  .rev-text {{ font-size:14px; margin-bottom:12px; }}
  .rev-text.muted {{ color:var(--ink-soft); font-style:italic; }}
  .reply {{ background:var(--cream); border:1px dashed var(--border); border-radius:10px; padding:12px 14px; }}
  .reply-label {{ font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:0.08em; color:var(--ink-soft); margin-bottom:8px; }}
  .reply textarea {{ width:100%; border:none; background:transparent; font-family:'Inter',sans-serif; font-size:14px; color:var(--ink); resize:vertical; line-height:1.5; }}
  .reply textarea:focus {{ outline:none; }}
  .reply-actions {{ display:flex; gap:14px; align-items:center; margin-top:10px; flex-wrap:wrap; }}
  .copy-btn {{ font-family:'Inter',sans-serif; font-size:13px; font-weight:600; background:var(--accent); color:#fff; border:none; border-radius:8px; padding:9px 16px; cursor:pointer; }}
  .copy-btn:hover {{ background:#a53a0c; }}
  .open-google {{ font-size:13px; color:var(--ink-soft); }}
  footer {{ text-align:center; color:var(--ink-soft); font-size:12px; margin-top:44px; padding-top:20px; border-top:1px solid var(--border); }}
  .toast {{ position:fixed; bottom:22px; left:50%; transform:translateX(-50%); background:var(--ink); color:var(--cream);
           padding:11px 18px; border-radius:10px; font-size:13px; opacity:0; pointer-events:none; transition:opacity 0.2s; z-index:50; }}
  .toast.show {{ opacity:1; }}
  @media (max-width:560px) {{ .stats {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="brand">Tavolo<span>Pieno</span></div>
    <h1>{_esc(name)}</h1>
    <div class="sub">Report privato · aggiornato il {_esc(updated)} · <strong>{_esc(rating if rating is not None else '—')}★</strong> su {_esc(review_count if review_count is not None else '—')} recensioni</div>
  </header>

  <div class="stats">
    <div class="stat"><div class="label">Voto attuale</div><div class="val">{_esc(rating if rating is not None else '—')}<small> / 5</small></div></div>
    <div class="stat"><div class="label">Recensioni totali</div><div class="val">{_esc(review_count if review_count is not None else '—')}</div></div>
    <div class="stat"><div class="label">Risposte pronte</div><div class="val">{n_drafts}</div></div>
  </div>

  <h2>📈 Andamento del voto</h2>
  <div class="panel">{_trend_svg(snapshots)}</div>

  <h2>📋 Checklist del profilo Google</h2>
  <div class="panel">{_checklist(snap)}</div>

  <h2>💬 Recensioni recenti e risposte pronte</h2>
{_review_cards(reviews, customer.get('place_id', ''))}

  <footer>
    Pagina privata — non condividere il link. · TavoloPieno 🍝<br>
    Le risposte sono bozze: rileggile sempre prima di pubblicarle su Google.
  </footer>
</div>
<div class="toast" id="toast"></div>
<script>
function toast(msg) {{
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove("show"), 2800);
}}
document.addEventListener("click", async (ev) => {{
  const btn = ev.target.closest(".copy-btn");
  if (!btn) return;
  const ta = document.getElementById(btn.dataset.target);
  if (!ta) return;
  try {{
    await navigator.clipboard.writeText(ta.value);
    toast("Risposta copiata! Ora incollala su Google.");
  }} catch {{
    ta.select();
    document.execCommand("copy");
    toast("Risposta copiata!");
  }}
}});
</script>
</body>
</html>
"""
