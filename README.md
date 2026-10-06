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
  delhaize/                    ← raw Delhaize receipt images + parsed OCR CSVs
  carrefour/                   ← parsed Carrefour source CSVs
  colruyt/                     ← parsed Colruyt source CSVs
  sessions/                    ← observe-mode recordings for scraper fixing

skills/
  delhaize.py                  ← Delhaize browser scraper
  mobile_receipts.py           ← Carrefour/Xtra Android ticket capture
  ocr_batch.py                 ← batch receipt OCR entry point
  ocr.py                       ← reusable vision-LLM receipt OCR wrapper
  source_normalizer.py         ← canonical schema + receipt-noise filter
  agent_remap.py               ← ingest receipts, product → pyfooda mapping (agent-driven)
  nutrition_report.py          ← nutrient report generation
```

See `skills/README.md` for the current pipeline (ingest → remap → report).

---

## Step 1 — Scrape groceries (Playwright)

**Install once:**
```bash
pip install playwright && playwright install chromium
```

```bash
python -m skills.delhaize    # → data/delhaize/*.jpg  (uses your Google Chrome login)
```

Carrefour and Colruyt tickets are available only in their Android apps. Set up
the persistent Google-Play emulator and capture their receipt screens using the
commands in `skills/README.md`.

**Delhaize + Chrome:** by default the scraper syncs cookies from your Chrome
profile into `.chrome_debug_profile/` (Chrome 136+ blocks debugging on the real
profile), may quit/reopen Chrome briefly, then downloads every receipt image.
Log into Delhaize in the opened window if prompted (up to 5 minutes).
Use `--no-chrome` only if you want a blank isolated profile.
Prefer `skills/README.md` for the current agent-centric pipeline.

### Automatic observe mode (self-recovery)

If the Delhaize scraper detects it is stuck — 3+ receipts in a row with no
image found — it **automatically switches to observe mode**:

```
  ⚠  SCRAPER STUCK — 3 consecutive receipts had no extractable image
  Observe mode ON.  In the browser window:
    1. Navigate to the correct page if needed
    2. Perform the steps you want the scraper to do
    3. Every click and navigation is being recorded below
    4. Close the browser window when finished
```

Every click and navigation is logged to the terminal and saved to
`data/sessions/observe_<timestamp>.json`.
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

Scans `data/delhaize/` — skips images that already have a sibling parsed CSV.
Model: `qwen/qwen-2-vl-7b-instruct` (~$0.03–0.08 / 100 receipts).

> Carrefour and Colruyt ticket screens are OCRed with `python -m skills.ocr`.

---

## Step 3 — Nutrient report

```bash
pip install pandas numpy pyfooda

python -m skills.agent_remap --ingest    # receipts CSVs → data/purchases_enriched.csv
python -m skills.agent_remap --generate  # list unmatched products for the agent
#   the coding agent fills data/agent_remap_responses.jsonl (see skills/README.md)
python -m skills.agent_remap --apply     # apply matches, re-enrich
python -m skills.nutrition_report        # generate HTML report
```

Report: `data/nutrition_report.html`, auto-deployed to
**GitHub Pages** on every push to `main`.

Matching is done by the coding agent (Copilot / Claude), not by a separate
matcher module. See `skills/README.md` for the response format and grams rules.

### Data-quality rules

- Receipt lines that are totals, payment, loyalty points or discounts are
  dropped at ingest (`skills/source_normalizer.py`).
- A matched product without a quantity (no label weight, no agent estimate)
  contributes nothing. The report shows how many rows carry a quantity; there
  is no silent 100 g default.
- Label quantities are parsed multipack-first (`6X33CL` → 1980 g, not 33 g).
  Volumes are taken as 1 ml = 1 g.
- Reference values are the EU Regulation 1169/2011 adult reference intakes,
  rescaled from 2000 to 2500 kcal. Fibre uses the EFSA adequate intake;
  cholesterol has no reference value.
- The report describes the nutrient composition of groceries bought, not what
  anyone ate.

---

## How the analysis works

1. Products matched to USDA foods via **FAISS** semantic similarity + **LLM** verification
2. Nutrients (per 100 g) scaled by extracted package weight in grams
3. Baskets **scaled to 2 500 kcal/day** for comparison against adult DRVs
4. Three interactive views: **Nutrients** / **Purchases** / **Unmatched**
