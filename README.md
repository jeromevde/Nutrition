# Nutrition Tracker

Personal nutrition tracking pipeline built on top of **Belgian supermarket receipts**
(Delhaize, Carrefour, Colruyt). Scrapes purchase data, maps products to the USDA
FoodData Central database via LLM + semantic search, and generates an interactive
HTML report with nutrient intake vs. DRVs.

---

## Repository layout

```
data/
  *.csv                        ← generated analysis CSVs
  nutrition_report.html        ← generated interactive report
  scrapers/
    delhaize/                  ← raw Delhaize receipt images + parsed OCR CSVs
    carrefour/                 ← parsed Carrefour source CSVs
    colruyt/                   ← parsed Colruyt source CSVs
    sessions/                  ← observe-mode recordings for scraper fixing

skills/
  scrapers/                    ← Delhaize, Carrefour, Colruyt browser scrapers
  pipeline/                    ← build mapping + nutrition report generation
  ocr_batch.py                 ← batch receipt OCR entry point
  matcher.py                   ← reusable semantic-search + LLM food matcher
  nutrition_estimator.py       ← LLM-estimated full nutrient profiles with confidence
  report_verifier.py           ← audits report outliers and suspicious mappings
  ocr.py                       ← reusable vision-LLM receipt OCR wrapper
  source_normalizer.py         ← canonical schema for future grocery sources
```

---

## Step 1 — Scrape groceries (Playwright)

Login sessions are remembered between runs (`.browser_profile/`).

**Install once:**
```bash
pip install playwright && playwright install chromium
```

```bash
python -m skills.scrapers.delhaize    # → data/scrapers/delhaize/*.jpg
python -m skills.scrapers.carrefour   # → data/scrapers/carrefour/carrefour_favorites.csv
python -m skills.scrapers.colruyt     # → data/scrapers/colruyt/colruyt_favorites.csv
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
`data/scrapers/sessions/observe_<timestamp>.json`.
Paste that file to an LLM to get a fixed scraper.

---

## Step 2 — OCR Delhaize receipts

Convert `.jpg` ticket images → structured CSVs (`product_name`, `price`, `barcode`):

```bash
export OPENROUTER_API_KEY="your-key-here"
pip install httpx

python -m skills.ocr_batch             # parallel (default)
python -m skills.ocr_batch --batch     # multi-image batching
python -m skills.ocr_batch --batch --batch-size 6
```

Scans `data/scrapers/delhaize/` — skips images that already have a sibling parsed CSV.
Model: `qwen/qwen-2-vl-7b-instruct` (~$0.03–0.08 / 100 receipts).

> Carrefour and Colruyt produce CSVs directly — no OCR step needed.

---

## Step 3 — Nutrient report

```bash
pip install pandas numpy pyfooda sentence-transformers faiss-cpu openai
export OPENROUTER_API_KEY="your-key-here"

python -m skills.pipeline.build_mapping       # map products → USDA foods
python -m skills.pipeline.nutrition_report    # generate HTML report
```

Report: `data/nutrition_report.html`, auto-deployed to
**GitHub Pages** on every push to `main`.

---

## LLM skills

The `skills/` package contains reusable modules for making the pipeline more
LLM-driven and easier to extend to new grocery sources.

```bash
python -m skills.source_normalizer data/scrapers/delhaize --source delhaize --output data/purchases_normalized.csv
python -m skills.matcher data/scrapers/delhaize --dry-run --output /tmp/matcher_candidates.csv --limit 25
python -m skills.nutrition_estimator --backend agent --limit 25
python -m skills.pipeline.nutrition_report
python -m skills.report_verifier
```

Suggested loop:

```text
scraper/OCR → source_normalizer → matcher → nutrition_report → report_verifier → targeted remap/fix
```

See `skills/README.md` for the skill-specific commands.

---

## How the analysis works

1. Products matched to USDA foods via **FAISS** semantic similarity + **LLM** verification
2. Nutrients (per 100 g) scaled by extracted package weight in grams
3. Baskets **scaled to 2 500 kcal/day** for comparison against adult DRVs
4. Three interactive views: **Nutrients** / **Purchases** / **Unmatched**
