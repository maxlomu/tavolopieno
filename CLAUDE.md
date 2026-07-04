# CLAUDE.md

This file orients Claude Code (and other AI coding assistants) working in this repo.

---

## Project: TavoloPieno

**One-line:** Lead-scoring pipeline + self-serve micro-SaaS for Italian restaurants: Google-profile monitoring with AI-drafted review replies.

**The business model (v0.2):** Two connected halves.
1. *Top of funnel (internal):* automatically detect Italian restaurants with digital gaps (weak Google Business Profile, declining reviews), rank them, and pitch the owners.
2. *The product (self-serve):* restaurants subscribe at **€49/month** (Stripe Payment Link) for weekly profile monitoring + review replies drafted in Italian by Claude, delivered via email digest + a private report page. The owner copy-pastes replies into Google — no account access needed. The original agency bundle (€149–€899/month: setup fees, broker commissions) remains the upsell path on top.

**Target market:** Italian restaurants first (~330K total, ~138K table-service). Bari is the current pilot city. Expansion to other Italian cities, then other countries, uses the same data pipeline.

---

## Current state of this repo (v0.2)

Both halves exist now.

### Lead-gen half (internal, unchanged since v0.1)

- `scripts/fetch_restaurants.py` — Outscraper search, 0–100 pain score, writes `docs/data.json`. Note: it does NOT fetch reviews (that moved to `analyze_trend.py`, on-demand per place_id).
- `scripts/analyze_trend.py`, `scripts/enrich_contacts.py`, `scripts/enrich_menu_photos.py` — on-demand enrichment, each with its own workflow.
- `docs/leads.html` — the internal leads dashboard (moved from `index.html` when the landing page took over the root).
- These scripts each embed their own copy of the Outscraper helpers **on purpose** — do not refactor them to import `outscraper_client.py`; the working pipeline stays untouched.

### SaaS half (the product)

- `docs/index.html` — public Italian landing page (€49/mo). The Stripe Payment Link is pasted by Max into the `STRIPE_PAYMENT_LINK` const near the bottom.
- `scripts/activate_customer.py` + workflow **"Attiva cliente"** — concierge onboarding: Max runs it with the payer's email + the restaurant's place_id after each Stripe notification. Generates a `secrets.token_urlsafe(16)` token, runs the first monitoring cycle, emails the welcome digest. Idempotent; reactivation keeps token/history.
- `scripts/monitor_customers.py` + workflow **"Report settimanali clienti"** (Tue 05:00 UTC cron + manual) — per active customer: one `maps/reviews-v3` call (snapshot + newest 30 reviews), diff on seen review ids, Claude drafts Italian replies (one batched call, `scripts/llm.py`), state updated, private report regenerated (`scripts/report.py` → `docs/r/<token>.html`), digest queued. Auto-deactivates customers whose Stripe subscription ended.
- `scripts/emailer.py` — Resend digests. Outbox pattern: monitoring writes `$RUNNER_TEMP/outbox.json`; the workflow commits, waits 90s for Pages to deploy, THEN sends (so links are live). Recipient emails are resolved from Stripe in memory at send time.
- `data/customers.json` — customer registry (token, place_id, restaurant_name, stripe_customer_id, plan, status). `data/state/<token>.json` — per-customer history. Both OUTSIDE `/docs` so Pages doesn't serve them. **NO emails or PII in the repo, ever — Stripe is the customer database.**
- Cost guardrails: `REVIEWS_LIMIT=30` per customer per run (~$0.09 Outscraper), `MAX_DRAFTS_PER_RUN=15` (claude-haiku-4-5, pennies).
- The two SaaS workflows share `concurrency: group: repo-commits` and push with a `git pull --rebase` retry loop (the four legacy workflows push bare and can race — accepted).

### Architecture choice — why it looks like this

The repo owner (Max) is a non-coder. The whole system is deliberately designed so he never has to open a terminal:

- GitHub Actions runs all code in the cloud
- GitHub Pages serves the dashboard from `/docs` (no build, no deploy)
- Refresh = click "Run workflow" in the Actions tab
- View = open `https://maxlomu.github.io/tavolopieno/`

**Do not introduce build steps, bundlers, frameworks, or anything requiring `npm install` / `pip install` on the user's machine unless you first confirm the alternative is worse.** If you add a dependency, it must install cleanly in the GitHub Actions workflow.

---

## Secrets (GitHub repo secrets — never commit any of them)

- `OUTSCRAPER_KEY` — Outscraper API (both halves).
- `STRIPE_KEY` — restricted Stripe key, read-only on Customers + Subscriptions (SaaS).
- `RESEND_KEY` — Resend email API (SaaS). Repo *variable* `RESEND_FROM` sets the from-address once a domain is verified.
- `ANTHROPIC_KEY` — Claude API for reply drafting (SaaS).

---

## Scoring logic (the business core)

The pain score (0–100, higher = better lead) is intentionally tuned to identify restaurants that are **struggling but recoverable**, not ones already dead:

| Component | Range | Key insight |
|---|---|---|
| Rating pain | 0–50 | Sweet spot is 3.5–4.2★ (actionable). <3.0 is too far gone, >4.5 has no pain. |
| Volume pain | 0–30 | <10 reviews = invisible. 100+ = healthy. |
| Trend pain | 0–20 | Last 5 reviews avg being 0.5★ below overall = declining. |

**Tiers:** Hot (70+) · Warm (50+) · Nurture (30+) · Low Priority (<30)

When modifying the scoring, preserve this intent: we want the **middle-of-the-market restaurant on a downslope**, not the absolute worst.

---

## Menu photo detection — current approach

Currently we flag "has at least one photo in any recent review" as a proxy for "there might be a menu picture." This is deliberately loose. Stricter detection (distinguishing menu photos from food/exterior photos) requires AI vision analysis per image — roadmapped but not yet added because of cost (~€0.01/photo via GPT-4o-mini).

---

## Data source

**Outscraper** (https://outscraper.cloud) is the current data provider. It wraps Google Maps with a friendlier async API and returns review photos as URLs (which Google's official Places API does not).

Relevant endpoints used:
- `GET /maps/search-v3` — find restaurants by query
- `GET /maps/reviews-v3` — fetch reviews by place_id, with photos

Both return async tasks with a `results_location` URL to poll. See `call_async()` in `fetch_restaurants.py`.

Outscraper pricing is pay-per-result (~$3/1000 reviews). Free tier covers ~100 reviews/month — enough to test on a few restaurants.

**Multi-country note:** Outscraper works globally with the same API. When expanding beyond Italy, just change the `CITY` and `QUERY` variables. The scoring logic is language-agnostic.

---

## Roadmap (what's NOT built yet)

Rough priority order. If Max asks for "the next thing," it's probably one of these:

1. **Auto-posting replies** via Google Business Profile API (customer OAuth + Google approval) — the natural premium tier above copy-paste drafts.
2. **Make city a parameter** — currently Bari is hardcoded in `fetch_restaurants.py`. Should be a workflow input or config file.
3. **GBP completeness signal in lead scoring** — the SaaS side already snapshots website/phone/hours/photos per customer; fold the same checks into `score_restaurant()`.
4. **Website health check** — fetch each restaurant's website, detect SSL, tech stack (BuiltWith-style), presence of online menu, presence of booking iframe.
5. **Review NLP analysis** — categorize negative review themes (food / service / price / cleanliness) using an LLM. Adds concrete talking points for outreach AND richer customer reports.
6. **Per-restaurant audit PDF generator** — the core sales tool. Takes one restaurant's data, produces a branded 4–6 page report to send as an outreach lead magnet.
7. **Menu vision analysis** — actually identify menu photos vs food/exterior using a vision LLM.
8. **Outreach orchestration** — email/direct-mail templates, sequencing, tracking.
9. **Provider integrations** — hooks for booking systems (Plateform), print brokers (Pixartprinting/Vistaprint affiliate links), compliance services.

---

## Italian-market context (important)

- **Do not use PEC addresses from INI-PEC for marketing.** Italian Garante has issued sanctions specifically for this (Provv. n. 149/2021). PEC is reachable but legally toxic for unsolicited commercial outreach.
- **Safe outreach channels in Italy:** info@ / prenotazioni@ email (B2B legitimate-interest defense), phone (after RPO check), direct mail (no consent needed for B2B).
- **Cultural note:** Italian restaurateurs average 53 years old, value personal relationships, trust their commercialista (accountant) more than any vendor. Outreach that references specific observed problems in their own GBP converts far better than generic pitches.
- **Key partner recommendations already decided:** Plateform (not TheFork) for booking referrals. Pixartprinting for menu print brokering. Reason: TheFork is resented in Italy for per-cover commissions; Plateform has an explicit partner/affiliate program with no per-cover fees.

---

## Coding conventions

- **Python:** standard library + `requests` only. No heavy deps. Type hints welcome but not required.
- **Frontend:** vanilla HTML/CSS/JS in a single file. Google Fonts is fine. No bundlers, no React build, no npm.
- **Data format:** `docs/data.json` is the contract between fetcher and leads dashboard; `data/state/<token>.json` is the contract between monitor and report renderer. Adding fields is fine; renaming/removing requires updating both sides.
- **Commits from CI:** the GitHub Actions commit as `github-actions[bot]` (`🔄 Refresh [city] restaurant data`, `🆕 Attiva cliente …`, `📬 Report settimanali clienti`). SaaS workflows push with a rebase-retry loop and share a concurrency group.
- **Privacy:** never write customer emails, names, or payment data into the repo — the repo is public. Stripe holds all PII.

---

## When in doubt

Ask Max. He is the product owner, speaks clearly about what he wants, and is comfortable saying "not sure yet" or asking for the simplest option. He will not understand framework jargon — explain in plain language, show before/after effects, and default to the lowest-complexity solution that works.
