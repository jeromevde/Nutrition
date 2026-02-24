# Nutrition Tracker

Personal nutrition tracking pipeline built on top of **Belgian supermarket receipts**
(Delhaize, Carrefour, Colruyt). It scrapes purchase data, maps products to the
USDA FoodData Central database via LLM + semantic search, and generates an
interactive HTML report with nutrient intake vs. DRVs.

---

## Repository layout

```
scrape_groceries.py            ← Entry point 0: browser scraper (Playwright)
batch_ocr_receipts.py          ← Entry point 1: OCR receipt photos → CSV
nutrient_analysis/
  01_build_mapping.py          ← Entry point 2a: map products → USDA foods (FAISS + LLM)
  02_nutrition_report.py       ← Entry point 2b: compute nutrients + build report
  output/
    purchases_enriched.csv     ← every purchase row with USDA match
    delhaize_mapping.csv       ← unique product → pyfooda mapping
    nutrition_report.html      ← the interactive report (deployed to GitHub Pages)
    nutrition_yearly.csv       ← yearly averages vs DRV
    nutrition_pertrip.csv      ← per-trip scaled nutrients
scrapers/
  delhaize/
    tickets/                   ← raw parsed CSVs
    scrape_delhaize_tickets.js ← legacy browser-console scraper
  colruyt/
  carrefour/
```

---

## Entry point 0 — Scrape groceries (Playwright)

Automated browser-based scraping. Opens a real browser, lets you log in,
then auto-downloads receipt data:

```bash
pip install playwright && playwright install chromium
python scrape_groceries.py                    # all stores
python scrape_groceries.py --store delhaize   # single store
python scrape_groceries.py --store carrefour
python scrape_groceries.py --store colruyt
```

Login sessions are remembered between runs (stored in `.browser_profile/`).

---

## Entry point 1 — OCR receipts (optional)

Convert `.jpg` receipt photos into structured CSVs:

```bash
export OPENROUTER_API_KEY="your-key-here"
pip install httpx
python3 batch_ocr_receipts.py            # single-image mode (parallel workers)
python3 batch_ocr_receipts.py --batch    # multi-image batching (fewer API calls)
python3 batch_ocr_receipts.py --batch --batch-size 6
```

- Recursively scans for all `.jpg` files
- Skips images that already have a matching `.csv`
- Default: 10 parallel single-image calls; `--batch` groups images per API call
- Uses `qwen/qwen-2-vl-7b-instruct` (~$0.03–0.08 / 100 receipts)

---

## Entry point 2 — Nutrient report

After receipts are parsed, build the report:

```bash
pip install pandas numpy pyfooda sentence-transformers faiss-cpu openai
export OPENROUTER_API_KEY="your-key-here"

cd nutrient_analysis

# Step 1: map product names → USDA foods (FAISS semantic search + LLM)
python 01_build_mapping.py

# Step 2: compute nutrients + generate the HTML report
python 02_nutrition_report.py
```

The report lands at `nutrient_analysis/output/nutrition_report.html` and is
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

---
