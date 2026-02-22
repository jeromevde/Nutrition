# Nutrition Tracker

Personal nutrition tracking pipeline built on top of **Delhaize supermarket receipts**.
It OCRs paper receipts, maps products to the USDA FoodData Central database via LLM,
and generates an interactive HTML report with nutrient intake vs. DRVs and most-purchased foods.

---

## Repository layout

```
batch_ocr_receipts.py          ← Entry point 1: OCR receipt photos → CSV
nutrient_analysis/
  01_build_mapping.py          ← Entry point 2a: map products → USDA foods
  02_nutrition_report.py       ← Entry point 2b: compute nutrients + build report
  output/
    purchases_enriched.csv     ← every purchase row with USDA match
    delhaize_mapping.csv       ← unique product → pyfooda mapping
    nutrition_report.html      ← the interactive report (deployed to GitHub Pages)
    nutrition_yearly.csv       ← yearly averages vs DRV
    nutrition_pertrip.csv      ← per-trip scaled nutrients
scrapers/
  delhaize/
    tickets/                   ← raw parsed CSVs from the JS scraper
    scrape_delhaize_tickets.js ← browser-side scraper for the Delhaize app
    parse_delhaize_tickets.py  ← alternative: local parsing
  colruyt/
  carrefour/
```

---

## Entry point 1 — OCR receipts

Convert `.jpg` receipt photos into structured CSVs:

```bash
export OPENROUTER_API_KEY="your-key-here"
pip install httpx
python3 batch_ocr_receipts.py
```

- Recursively scans for all `.jpg` files
- Skips images that already have a matching `.csv`
- Runs up to 10 requests in parallel (configurable via `MAX_WORKERS`)
- Uses `qwen/qwen-2-vl-7b-instruct` — ~50× cheaper than GPT-4o (~$0.03–0.08 / 100 receipts)
- Each image produces a CSV with columns: `product_name`, `price`, `barcode`

---

## Entry point 2 — Nutrient report

After receipts are parsed (either via OCR or the JS scraper), build the report:

```bash
pip install pandas numpy pyfooda rank_bm25 openai
export OPENROUTER_API_KEY="your-key-here"

cd nutrient_analysis

# Step 1: map Delhaize product names → USDA FoodData Central entries
python 01_build_mapping.py

# Step 2: compute nutrients + generate the HTML report
python 02_nutrition_report.py
```

The report lands at `nutrient_analysis/output/nutrition_report.html` and is
automatically deployed to **GitHub Pages** on every push to `main`.

---

## How the analysis works

1. Each purchase row is matched to a USDA food entry by an LLM (via BM25 candidates).
2. Nutrient values (per 100 g, USDA standard) are scaled by the grams extracted from
   the product name (or a default serving size when unavailable).
3. Each shopping basket is **scaled to 2 500 kcal/day** so baskets of different sizes
   are comparable and can be judged against adult Dietary Reference Values (DRVs).
4. The report shows two interactive views:
   - **Nutrients** — % of DRV per year with top contributing foods per nutrient
   - **Most Bought Foods** — purchase frequency with per-food nutrient profile

---
