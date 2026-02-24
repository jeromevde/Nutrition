# Nutrition Tracker

Personal nutrition tracking pipeline built on top of **Belgian supermarket receipts**
(Delhaize, Carrefour, Colruyt). It scrapes purchase data, maps products to the
USDA FoodData Central database via LLM + semantic search, and generates an
interactive HTML report with nutrient intake vs. DRVs.

---

## Repository layout

```
scrape_extract_data/               ← Step 1 & 2: scrape + OCR
  scrape_delhaize.py               ← download Delhaize ticket images (.jpg)
  scrape_carrefour.py              ← scrape Carrefour frequently-purchased items
  scrape_colruyt.py                ← scrape Colruyt favourites
  batch_ocr_receipts.py            ← OCR ticket images → CSV

nutrient_analysis/                 ← Step 3: map + report
  01_build_mapping.py              ← map products → USDA foods (FAISS + LLM)
  02_nutrition_report.py           ← compute nutrients + build HTML report
  output/
    purchases_enriched.csv         ← every purchase row with USDA match
    delhaize_mapping.csv           ← unique product → pyfooda mapping
    nutrition_report.html          ← the interactive report (→ GitHub Pages)
    nutrition_yearly.csv           ← yearly averages vs DRV
    nutrition_pertrip.csv          ← per-trip scaled nutrients

scrapers/
  delhaize/
    tickets/                       ← raw ticket images (.jpg) + parsed CSVs
    scrape_delhaize_tickets.js     ← legacy browser-console scraper
  colruyt/
    colruyt_favorites.csv
  carrefour/
    favorite_items.csv
```

---

## Step 1 — Scrape groceries (Playwright)

Automated browser-based scraping. Opens a real browser window, lets you log in,
then auto-downloads receipt data. Login sessions are remembered between runs
(stored in `.browser_profile/`).

**Install once:**
```bash
pip install playwright && playwright install chromium
```

**Delhaize** — downloads receipt ticket images as `.jpg` files:
```bash
python scrape_extract_data/scrape_delhaize.py
```

**Carrefour** — scrapes frequently-purchased product names:
```bash
python scrape_extract_data/scrape_carrefour.py
```

**Colruyt** — scrapes favourite product names:
```bash
python scrape_extract_data/scrape_colruyt.py
```

> Each script opens the relevant page and waits up to 5 minutes for you to log in.
> Once the expected page elements appear, scraping starts automatically.

---

## Step 2 — OCR Delhaize receipts

Convert the downloaded `.jpg` ticket images into structured CSVs
(`product_name`, `price`, `barcode`):

```bash
export OPENROUTER_API_KEY="your-key-here"   # get one at openrouter.ai/keys
pip install httpx

python scrape_extract_data/batch_ocr_receipts.py              # parallel (default)
python scrape_extract_data/batch_ocr_receipts.py --batch      # multi-image batching
python scrape_extract_data/batch_ocr_receipts.py --batch --batch-size 6
```

- Scans `scrapers/` recursively for all `.jpg` files
- Skips images that already have a matching `.csv` — safe to re-run
- Default: 10 parallel single-image calls; `--batch` groups images per API call
- Model: `qwen/qwen-2-vl-7b-instruct` (~$0.03–0.08 / 100 receipts)

> **Carrefour and Colruyt** scrapers produce CSVs directly — no OCR step needed.

---

## Step 3 — Nutrient report

After all CSVs are in place, build the nutrition mapping and HTML report:

```bash
pip install pandas numpy pyfooda sentence-transformers faiss-cpu openai
export OPENROUTER_API_KEY="your-key-here"

cd nutrient_analysis

# 3a: map product names → USDA foods (FAISS semantic search + LLM)
python 01_build_mapping.py

# 3b: compute nutrients + generate the interactive HTML report
python 02_nutrition_report.py
```

The report is written to `nutrient_analysis/output/nutrition_report.html` and is
automatically deployed to **GitHub Pages** on every push to `main`.

---

## How the analysis works

1. Each product name is matched to a USDA food entry using **FAISS** semantic
   similarity (sentence-transformers) to find top candidates, then an **LLM**
   picks the best match and infers the package weight in grams.
2. Nutrient values (per 100 g, USDA standard) are scaled by the extracted grams.
3. Each shopping basket is **scaled to 2 500 kcal/day** so baskets of different sizes
   are comparable and can be judged against adult Dietary Reference Values (DRVs).
4. The report shows three interactive views:
   - **Nutrients** — avg % of DRV per year, click any row to see top contributing foods
   - **Purchases** — all items grouped by date or by name (original → matched)
   - **Unmatched** — items the LLM couldn't map, for debugging and improving coverage
