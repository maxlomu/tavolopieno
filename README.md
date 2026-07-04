# TavoloPieno 🍝

Two halves, one repo:

1. **Lead scoring** (internal): finds Italian restaurants with digital pain and ranks them — Max's prospecting tool.
2. **Micro-SaaS** (the product): restaurants pay **€49/mese** for weekly Google-profile monitoring + review replies drafted in Italian, ready to copy-paste.

| Page | URL |
|---|---|
| 🏪 Public landing page | `https://maxlomu.github.io/tavolopieno/` |
| 📊 Internal leads dashboard | `https://maxlomu.github.io/tavolopieno/leads.html` |
| 🔒 Customer reports (private links) | `https://maxlomu.github.io/tavolopieno/r/<token>.html` |

Everything runs on GitHub Actions + GitHub Pages. No terminal, no servers, ever.

---

## One-time setup — lead-gen half (done already)

1. **Secret `OUTSCRAPER_KEY`** — repo → Settings → Secrets and variables → Actions → New repository secret.
2. **GitHub Pages** — Settings → Pages → Deploy from branch `main`, folder `/docs`.
3. **Actions write access** — Settings → Actions → General → Workflow permissions → Read and write.

Refresh leads any time: **Actions → Fetch Bari restaurants → Run workflow** (also runs Mondays 6am UTC).

---

## 💶 One-time setup — SaaS half (do this once, ~30 minutes)

### 1. Stripe (payments + customer database)

1. Create an account at [stripe.com](https://stripe.com). Start in **test mode** (toggle top-right).
2. **Products → Add product**: name `TavoloPieno Base`, recurring price **€49/month**.
3. **Payment Links → New**: pick that product. Under *Options*:
   - collect the customer's **email** (on by default),
   - add a **custom field**: "Nome ristorante e città" (text, required).
4. Copy the Payment Link URL and paste it in `docs/index.html` — look for the line
   `const STRIPE_PAYMENT_LINK = "";` near the bottom (there's a comment saying *MAX: incolla qui il link Stripe*). You can edit the file directly on GitHub (pencil icon).
5. **Developers → API keys → Create restricted key**: give it **Read** access to *Customers* and *Subscriptions* only. Save it as repo secret **`STRIPE_KEY`**.

> ⚠️ While testing, use the test-mode key and test-mode Payment Link. Pay with card `4242 4242 4242 4242`, any future date, any CVC. When you're ready to go live: switch Stripe to live mode, make a live Payment Link + restricted key, and swap both in.

### 2. Resend (sends the emails)

1. Create an account at [resend.com](https://resend.com) (free: 100 emails/day).
2. **API Keys → Create** → save as repo secret **`RESEND_KEY`**.
3. ⚠️ **Important:** until you verify a domain, Resend only delivers to **your own email address**, from `onboarding@resend.dev`. That's fine for testing. Before real customers:
   - buy a domain (e.g. `tavolopieno.it`, ~€10/anno),
   - add it in Resend → Domains and set the DNS records they show you,
   - then add a repo **variable** (Settings → Secrets and variables → Actions → *Variables* tab) named **`RESEND_FROM`** with value like `TavoloPieno <report@tavolopieno.it>`.

### 3. Anthropic (writes the review replies)

1. Create an API key at [console.anthropic.com](https://console.anthropic.com) (a few € of credit lasts months — each customer-week costs well under 1 cent).
2. Save it as repo secret **`ANTHROPIC_KEY`**.

---

## 🧑‍🍳 Daily operations

### A new customer paid — activate them (~2 minutes)

1. Stripe emails you about the new subscription. Open it: you'll see the customer's **email** and the **restaurant name & city** they typed.
2. Find the restaurant's **place_id**: it's in the leads dashboard (`/leads.html`, link on each restaurant) or search the name on Google Maps and copy the id from Outscraper/URL.
3. Repo → **Actions → Attiva cliente → Run workflow**:
   - `customer` = the email they paid with,
   - `place_id` = the restaurant's place_id,
   - `action` = `activate`.
4. Done. The workflow fetches their profile, writes the first report, and emails them their private link.

### Every week, automatically

The **Report settimanali clienti** workflow runs every **Tuesday 05:00 UTC**: checks every active customer's profile, drafts replies to new reviews, refreshes their private page, and emails the digest (an ⚠️-subject alert if a 1–2★ review arrived). You can also run it manually from the Actions tab any time.

### A customer cancels

Nothing to do: the weekly run checks Stripe and stops monitoring automatically. To stop someone immediately, run **Attiva cliente** with `action = deactivate` and their `place_id`.

---

## How the lead score works (internal half)

Each restaurant gets a 0–100 "pain score" — higher = better sales lead:

| Signal | Max points | Logic |
|---|---|---|
| Rating pain | 50 | Sweet spot 3.5–4.2★ (actionable pain). <3.0 probably dying, >4.5 no pain. |
| Volume pain | 30 | <10 reviews = invisible. 100+ = healthy. |
| Trend pain | 20 | Last 5 reviews avg 0.5★ below overall = declining (on-demand analysis). |

**Tiers:** Hot (70+) · Warm (50+) · Nurture (30+) · Low Priority (<30)

---

## Files

```
tavolopieno/
├── scripts/
│   ├── fetch_restaurants.py     # lead-gen: fetch + score Bari restaurants
│   ├── analyze_trend.py         # lead-gen: on-demand review trend per restaurant
│   ├── enrich_contacts.py       # lead-gen: email/contact enrichment
│   ├── enrich_menu_photos.py    # lead-gen: menu photo enrichment
│   ├── outscraper_client.py     # SaaS: shared Outscraper helpers
│   ├── stripe_client.py         # SaaS: Stripe = customer DB (read-only key)
│   ├── llm.py                   # SaaS: Claude drafts Italian review replies
│   ├── emailer.py               # SaaS: Resend digests (outbox pattern)
│   ├── report.py                # SaaS: renders private report pages
│   ├── activate_customer.py     # SaaS: concierge onboarding
│   └── monitor_customers.py     # SaaS: the weekly engine
├── data/
│   ├── customers.json           # registry: token + place_id + status (NO emails/PII)
│   └── state/<token>.json       # per-customer history (reviews seen, snapshots)
├── .github/workflows/           # all automation (fetch, enrich, activate, monitor)
└── docs/                        # GitHub Pages
    ├── index.html               # public landing page
    ├── leads.html               # internal leads dashboard
    ├── data.json                # lead data
    └── r/<token>.html           # private customer reports
```

**Privacy rule:** customer emails and payment data live **only in Stripe**. The repo stores nothing personal — just the restaurant's public place_id and an anonymous token.

---

## What's next

- [ ] Verified sending domain + branded from-address (see Resend setup above)
- [ ] Auto-posting replies via Google Business Profile API (customer OAuth) as a premium tier
- [ ] Swap Bari → any Italian city (workflow input)
- [ ] Per-restaurant audit PDFs as outreach lead magnet
- [ ] Review theme analysis (food/service/price) for richer reports
