# Skills

Agent-centric nutrition pipeline. Matching is done by the coding agent (Copilot / Claude), not by deterministic heuristics or external LLM providers.

## Pipeline

```bash
# 1. Ingest receipts (Delhaize uses your Google Chrome login by default)
pip install playwright && playwright install chromium   # once
python -m skills.delhaize          # may quit/reopen Chrome briefly to sync cookies
python -m skills.ocr_batch         # OCR image receipts into CSVs

# 2. Find what needs matching
python -m skills.agent_remap --generate
# → data/agent_remap_requests.jsonl (product name, count, price, weight hint)

# 3. Agent fills data/agent_remap_responses.jsonl
# Each line: {"product_name": "...", "pyfooda_name": "...", "grams": 250}
# Non-food:  {"product_name": "...", "action": "ignore"}

# 4. Apply + re-enrich
python -m skills.agent_remap --apply

# 5. Report
python -m skills.nutrition_report
```

To re-enrich purchases from the existing mapping (no new matches needed):
```bash
python -m skills.agent_remap --enrich
```

## Carrefour and Colruyt mobile tickets

Carrefour and Colruyt keep receipts in their apps, so this repository uses one
persistent Android emulator. It has Google Play and retains the Play Store and
retailer sessions across restarts. Credentials never leave the emulator.

```bash
# One time: Android SDK packages and a Google-Play-enabled Pixel emulator
python -m skills.mobile_receipts setup

# Each session
python -m skills.mobile_receipts start
python -m skills.mobile_receipts install carrefour  # install Carrefour België once
python -m skills.mobile_receipts install colruyt    # install Xtra once
python -m skills.mobile_receipts login carrefour
python -m skills.mobile_receipts login colruyt
```

Authenticate in the emulator window. For Xtra, enable `Profiel → Kastickets →
Digitale kastickets en garanties → Enkel digitale kastickets` so future
receipts arrive there automatically.

To extract a receipt, open it in its app, count the visible screens while
scrolling, then capture it. The command saves raw receipt screens; it does not
try to automate an app UI that can change without notice.

```bash
python -m skills.mobile_receipts capture carrefour 2026-07-18 --pages 3
python -m skills.ocr data/carrefour/2026_07_18_01.png data/carrefour/2026_07_18_02.png data/carrefour/2026_07_18_03.png --output-dir data/carrefour
```

## Skills

| Skill | Purpose |
|-------|---------|
| `agent_remap.py` | **Main entry point.** Generate requests, apply responses, enrich purchases, sanitize stale keys. |
| `nutrition_report.py` | Compute per-trip/yearly nutrients, generate HTML report. |
| `source_normalizer.py` | Normalize raw scraper/OCR CSVs into canonical schema. |
| `common.py` | Shared utilities: pyfooda access, search index, paths, JSON helpers. |
| `delhaize.py` | Delhaize receipt scraper. **Agent-first:** run `python -m skills.delhaize` (Chrome cookies by default). See module docstring. |
| `mobile_receipts.py` | Google-Play Android emulator and receipt-screen capture for Carrefour and Xtra. |
| `ocr.py` | OCR a single receipt image. |
| `ocr_batch.py` | Batch OCR over multiple receipts. |
| `observe.py` | Browser observe-mode fallback for scrapers. |
| `llm_client.py` | LLM provider client factory (used by OCR). |

## Agent response format

```jsonl
{"product_name": "APPEL PINK LADY 6P", "pyfooda_name": "APPLE", "grams": 900}
{"product_name": "500G DE CECCO GNOC", "pyfooda_name": "GNOCCHI", "grams": 500}
{"product_name": "ORAL B PREC CL REF", "action": "ignore"}
```

**Grams rules for agent:**
- Use explicit weight from label first (`500G` → 500, `1KG` → 1000)
- Infer from piece count × typical unit weight:
  - apple/pear ~150g, banana ~120g, orange ~200g, lemon ~100g, avocado ~170g, egg ~60g
- Infer from price when weight is unknown (e.g. butter €2/250g, salmon €4/150g)
- Omit grams if truly unknown — report falls back to 100g default
