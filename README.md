# Nutrition Tracker

Personal nutrition tracking pipeline built on top of **Belgian supermarket receipts**
(Delhaize, Carrefour, Colruyt). Scrapes purchase data, maps products to the USDA
FoodData Central database via LLM + semantic search, and generates an interactive
HTML report with nutrient intake vs. DRVs.

---

## Repository layout

```
scrape_extract_data/
  scrape_delhaize.py           ← Step 1a: download Delhaize ticket images (.jpg)
  scrape_carrefour.py          ← Step 1b: scrape Carrefour frequently-purchased items
  scrape_colruyt.py            ← Step 1c: scrape Colruyt favourites
  batch_ocr_receipts.py        ← Step 2:  OCR ticket images → CSV
  _observe.py                  ← shared observe-mode module (auto-triggered on failure)
  delhaize/
  carrefour/
  colruyt/
  sessions/                    ← observe-mode recordings, auto-created on failure, user performs some actions
                                 saves logs for LLM-based scraper fixing

nutrient_analysis/
  01_build_mapping.py          ← Step 3a: map products → USDA foods (FAISS + LLM)
  02_nutrition_report.py       ← Step 3b: compute nutrients + build HTML report
  output/
    a_few_csvs_with_data.csv...
    nutrition_report.html      ← deployed to GitHub Pages on push to main
```

---

## Step 1 — Scrape groceries (Playwright)

Login sessions are remembered between runs (`.browser_profile/`).

**Install once:**
```bash
pip install playwright && playwright install chromium
```

```bash
python scrape_extract_data/scrape_delhaize.py    # → delhaize/*.jpg
python scrape_extract_data/scrape_carrefour.py   # → carrefour/carrefour_favorites.csv
python scrape_extract_data/scrape_colruyt.py     # → colruyt/colruyt_favorites.csv
```

Each script waits up to 5 minutes for login, then scrapes automatically.

### Automatic observe mode (self-recovery)

If a scraper detects it is stuck — 3+ receipts in a row with no image found
(Delhaize), or 0 items extracted after loading (Carrefour/Colruyt) — it
**automatically switches to observe mode**:

```
  ⚠  SCRAPER STUCK — 3 consecutive receipts had no extractable image
  Observe mode ON.  In the browser window:
    1. Navigate to the correct page if needed
    2. Perform the steps you want the scraper to do
    3. Every click and navigation is being recorded below
    4. Close the browser window when finished
```

Every click and navigation is logged to the terminal and saved to
`scrape_extract_data/sessions/observe_<timestamp>.json`.
Paste that file to an LLM to get a fixed scraper.

---

## Step 2 — OCR Delhaize receipts

Convert `.jpg` ticket images → structured CSVs (`product_name`, `price`, `barcode`):

```bash
export OPENROUTER_API_KEY="your-key-here"
pip install httpx

python scrape_extract_data/batch_ocr_receipts.py             # parallel (default)
python scrape_extract_data/batch_ocr_receipts.py --batch     # multi-image batching
python scrape_extract_data/batch_ocr_receipts.py --batch --batch-size 6
```

Scans `scrape_extract_data/delhaize/` — skips already-processed images.
Model: `qwen/qwen-2-vl-7b-instruct` (~$0.03–0.08 / 100 receipts).

> Carrefour and Colruyt produce CSVs directly — no OCR step needed.

---

## Step 3 — Nutrient report

```bash
pip install pandas numpy pyfooda sentence-transformers faiss-cpu openai
export OPENROUTER_API_KEY="your-key-here"

cd nutrient_analysis
python 01_build_mapping.py      # map products → USDA foods
python 02_nutrition_report.py   # generate HTML report
```

Report: `nutrient_analysis/output/nutrition_report.html`, auto-deployed to
**GitHub Pages** on every push to `main`.

---

## How the analysis works

1. Products matched to USDA foods via **FAISS** semantic similarity + **LLM** verification
2. Nutrients (per 100 g) scaled by extracted package weight in grams
3. Baskets **scaled to 2 500 kcal/day** for comparison against adult DRVs
4. Three interactive views: **Nutrients** / **Purchases** / **Unmatched**
