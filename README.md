# TavoloPieno 🍝

Signal-based lead scoring for Italian restaurants.

**Live dashboard:** `https://maxlomu.github.io/tavolopieno/` *(after setup below)*

---

## What this does

1. Fetches 10 restaurants in Bari from Google Maps (via Outscraper)
2. Pulls their recent reviews, including any photos customers posted
3. Scores each restaurant on "pain level" (low rating + few reviews + declining trend = higher score)
4. Flags which ones have photos in their reviews (menu candidate signal)
5. Shows everything on a clean web dashboard

---

## One-time setup (5 minutes, no terminal needed)

### 1. Add your Outscraper API key to GitHub

Go to your repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

- **Name:** `OUTSCRAPER_KEY`
- **Value:** *your Outscraper API key*

*(You mentioned you already did this — skip if done.)*

### 2. Enable GitHub Pages

Go to **Settings** → **Pages**

- **Source:** Deploy from a branch
- **Branch:** `main` · folder: `/docs`
- Click **Save**

After ~1 minute, your dashboard will be live at:
**`https://maxlomu.github.io/tavolopieno/`**

### 3. Allow Actions to write to the repo

Go to **Settings** → **Actions** → **General** → scroll to **Workflow permissions**

- Select **Read and write permissions**
- Click **Save**

---

## How to refresh the data

Any time you want fresh data:

1. Go to the repo's **Actions** tab
2. Click **Fetch Bari restaurants** in the left sidebar
3. Click **Run workflow** → **Run workflow** (green button)
4. Wait ~2–3 minutes
5. Reload your dashboard URL

The workflow also runs automatically every Monday at 6am UTC.

---

## How the score works

Each restaurant gets a 0–100 "pain score" — higher means **better sales lead**:

| Signal | Max points | Logic |
|---|---|---|
| Rating pain | 50 | Sweet spot 3.5–4.2 ★ (actionable pain). <3.0 means probably dying, >4.5 means no pain. |
| Volume pain | 30 | <10 reviews = low visibility. 100+ reviews = healthy. |
| Trend pain | 20 | Last 5 reviews avg < overall avg by 0.5★ = declining. |

**Tiers:** Hot (70+) · Warm (50+) · Nurture (30+) · Low Priority (<30)

---

## Menu photo detection

Right now, we flag restaurants whose customers have **uploaded photos in reviews**. This is a proxy for "there's visual content about this place" — often photos of food/menus.

A stricter version (actually identifying whether a photo is a menu vs a plate) would require AI vision analysis per image (e.g., GPT-4o-mini at ~$0.01/photo). We'll add that when it's worth the cost.

---

## Files

```
tavolopieno/
├── scripts/
│   └── fetch_restaurants.py    # Calls Outscraper, scores, saves data.json
├── .github/workflows/
│   └── fetch.yml               # Runs the script on-demand or weekly
└── docs/
    ├── index.html              # The dashboard (standalone, no build)
    └── data.json               # Generated data the dashboard reads
```

---

## What's next

- [ ] Swap Bari → any Italian city (just change `CITY` in `fetch_restaurants.py`)
- [ ] Add website existence check (GBP completeness signal)
- [ ] Add review sentiment analysis (NLP on review text)
- [ ] Generate per-restaurant audit PDFs
- [ ] Build the outreach pipeline (cold email + direct mail)
