# CLAUDE.md

This file orients Claude Code (and other AI coding assistants) working in this repo.

---

## Project: TavoloPieno

**One-line:** A signal-based lead-scoring and outreach platform for Italian restaurants.

**The business model:** Automatically detect Italian restaurants with detectable digital gaps (weak Google Business Profile, declining reviews, no online menu, no booking system), then contact the owner with a personalized audit and sell them a bundle of services to fix those gaps. Hybrid revenue: direct subscriptions (€149–€899/month) + one-off setup fees + broker commissions from service providers (print shops, booking systems).

**Target market:** Italian restaurants first (~330K total, ~138K table-service). Bari is the current pilot city. Expansion to other Italian cities, then other countries, uses the same data pipeline.

---

## Current state of this repo (v0.1)

Very early. Only the **data-collection and lead-scoring half** exists so far. The outreach/service-delivery half is not built yet.

### What works now

- `scripts/fetch_restaurants.py` — calls Outscraper API to fetch N restaurants in a target city, pulls their recent reviews, computes a 0–100 "pain score" per restaurant, flags whether reviews contain photos (menu-candidate signal), and writes `docs/data.json`.
- `.github/workflows/fetch.yml` — runs the script on-demand (manual `workflow_dispatch`) or weekly (Monday 6am UTC), commits the updated `data.json` back to the repo.
- `docs/index.html` — standalone single-file dashboard (vanilla HTML/CSS/JS, no build step) served via GitHub Pages. Reads `data.json` and renders a ranked leaderboard.

### Architecture choice — why it looks like this

The repo owner (Max) is a non-coder. The whole system is deliberately designed so he never has to open a terminal:

- GitHub Actions runs all code in the cloud
- GitHub Pages serves the dashboard from `/docs` (no build, no deploy)
- Refresh = click "Run workflow" in the Actions tab
- View = open `https://maxlomu.github.io/tavolopieno/`

**Do not introduce build steps, bundlers, frameworks, or anything requiring `npm install` / `pip install` on the user's machine unless you first confirm the alternative is worse.** If you add a dependency, it must install cleanly in the GitHub Actions workflow.

---

## Secrets

- `OUTSCRAPER_KEY` — stored in GitHub repo secrets. Used by the workflow only. Never commit it.

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

1. **Make city a parameter** — currently Bari is hardcoded. Should be a workflow input or config file.
2. **GBP completeness signal** — check website presence, phone, hours, photo count. Extends `score_restaurant()`.
3. **Website health check** — fetch each restaurant's website, detect SSL, tech stack (BuiltWith-style), presence of online menu, presence of booking iframe.
4. **Review NLP analysis** — categorize negative review themes (food / service / price / cleanliness) using an LLM. Adds concrete talking points for outreach.
5. **Per-restaurant audit PDF generator** — the core sales tool. Takes one restaurant's data, produces a branded 4–6 page report to send as an outreach lead magnet.
6. **Menu vision analysis** — actually identify menu photos vs food/exterior using a vision LLM.
7. **Outreach orchestration** — email/direct-mail templates, sequencing, tracking.
8. **Provider integrations** — hooks for booking systems (Plateform), print brokers (Pixartprinting/Vistaprint affiliate links), compliance services.

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
- **Data format:** `docs/data.json` is the contract between fetcher and dashboard. Adding fields is fine; renaming/removing requires updating both sides.
- **Commits from CI:** the GitHub Action commits as `github-actions[bot]` with message `🔄 Refresh [city] restaurant data`.

---

## When in doubt

Ask Max. He is the product owner, speaks clearly about what he wants, and is comfortable saying "not sure yet" or asking for the simplest option. He will not understand framework jargon — explain in plain language, show before/after effects, and default to the lowest-complexity solution that works.
