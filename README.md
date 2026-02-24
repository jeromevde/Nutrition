# Nutrition Tracker

Personal nutrition tracking pipeline built on top of **Belgian supermarket receipts**
(Delhaize, Carrefour, Colruyt). It scrapes purchase data, maps products to the
USDA FoodData Central database via LLM + semantic search, and generates an
interactive HTML report with nutrient intake vs. DRVs.

---

## Repository layout

```
scrape_extract_data/
  scrape_delhaize.py           ← Step 1a: download Delhaize ticket images (.jpg)
  scrape_carrefour.py          ← Step 1b: scrape Carrefour frequently-purchased items
  scrape_colruyt.py            ← Step 1c: scrape Colruyt favourites
  batch_ocr_receipts.py        ← Step 2:  OCR ticket images → CSV
  explore_websites.py          ← Tool:    record a browser session → scraper blueprint
  tickets/                     ← Delhaize ticket images (.jpg) + parsed CSVs
  carrefour_favorites.csv      ← Carrefour product list
  colruyt_favorites.csv        ← Colruyt product list
  sessions/                    ← Saved browser session recordings (auto-created)

nutrient_analysis/
  01_build_mapping.py          ← Step 3a: map products → USDA foods (FAISS + LLM)
  02_nutrition_report.py       ← Step 3b: compute nutrients + build HTML report
  output/
    purchases_enriched.csv     ← every purchase row with USDA match
    delhaize_mapping.csv       ← unique product → pyfooda mapping
    nutrition_report.html      ← the interactive report (→ GitHub Pages)
    nutrition_yearly.csv       ← yearly averages vs DRV
    nutrition_pertrip.csv      ← per-trip scaled nutrients
```

---

## Step 1 — Scrape groceries (Playwright)

Automated browser scraping. Opens a real browser window, lets you log in,
then auto-downloads receipt data. Login sessions are remembered between runs
(stored in `.browser_profile/`).

**Install once:**
```bash
pip install playwright && playwright install chromium
```

> ⚠️  If you see an error about `Failed to create a ProcessSingleton` or a
> `SingletonLock` file when launching a script, close any other browser
> windows that are using `.browser_profile` (or delete
> `.browser_profile/SingletonLock`). The scrapers now automatically remove
> stale lock files before startup.


**Delhaize** — downloads receipt images as `.jpg` files into `scrape_extract_data/tickets/`:
```bash
python scrape_extract_data/scrape_delhaize.py
```

**Carrefour** — scrapes frequently-purchased items → `scrape_extract_data/carrefour_favorites.csv`:
```bash
python scrape_extract_data/scrape_carrefour.py
```

**Colruyt** — scrapes favourites → `scrape_extract_data/colruyt_favorites.csv`:
```bash
python scrape_extract_data/scrape_colruyt.py
```

> Each script waits up to 5 minutes for you to log in.
> Once the expected page elements appear, scraping starts automatically.

---

## Step 2 — OCR Delhaize receipts

Convert `.jpg` ticket images → structured CSVs (`product_name`, `price`, `barcode`):

```bash
export OPENROUTER_API_KEY="your-key-here"   # get one at openrouter.ai/keys
pip install httpx

python scrape_extract_data/batch_ocr_receipts.py             # parallel (default)
python scrape_extract_data/batch_ocr_receipts.py --batch     # multi-image batching
python scrape_extract_data/batch_ocr_receipts.py --batch --batch-size 6
```

- Scans `scrape_extract_data/tickets/` for all `.jpg` files
- Skips images that already have a matching `.csv` — safe to re-run
- Uses `qwen/qwen-2-vl-7b-instruct` (~$0.03–0.08 / 100 receipts)

> Carrefour and Colruyt scrapers produce CSVs directly — no OCR step needed.

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

## Tool — Record a browser session (explore_websites.py)

When a website changes its layout and a scraper breaks, use this tool to quickly
show the agent how to navigate the new layout. It opens a monitored browser,
records every click, navigation and network request to a JSON file, and you can
feed that file to an LLM to regenerate the scraper.

```bash
python scrape_extract_data/explore_websites.py
python scrape_extract_data/explore_websites.py --url https://www.delhaize.be/nl/my-account/loyalty/tickets
```

**Workflow:**
1. Run the script above — a browser opens
2. Log in and perform the actions you want to automate
3. Close the window — session saved to `scrape_extract_data/sessions/<timestamp>.json`
4. Paste the JSON into your LLM:
   > "Write a Playwright Python scraper that reproduces these user actions and
   >  saves the data to `scrape_extract_data/`."

---

## How the analysis works

1. Each product name is matched to a USDA food entry using **FAISS** semantic
   similarity (sentence-transformers) to find top candidates, then an **LLM**
   picks the best match and infers the package weight in grams.
2. Nutrient values (per 100 g, USDA standard) are scaled by the extracted grams.
3. Each shopping basket is **scaled to 2 500 kcal/day** so baskets of different
   sizes are comparable and can be judged against adult Dietary Reference Values (DRVs).
4. The report shows three interactive views:
   - **Nutrients** — avg % of DRV per year, click any row to see top contributing foods
   - **Purchases** — all items grouped by date or by name (original → matched)
   - **Unmatched** — items the LLM couldn't map, for debugging and improving coverage
