# Skills

Agent-centric nutrition pipeline. Matching is done by the coding agent (Copilot / Claude), not by deterministic heuristics or external LLM providers.

## Pipeline

```bash
# 1. Ingest receipts
python -m skills.delhaize          # scrape Delhaize
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

## Skills

| Skill | Purpose |
|-------|---------|
| `agent_remap.py` | **Main entry point.** Generate requests, apply responses, enrich purchases, sanitize stale keys. |
| `nutrition_report.py` | Compute per-trip/yearly nutrients, generate HTML report. |
| `source_normalizer.py` | Normalize raw scraper/OCR CSVs into canonical schema. |
| `common.py` | Shared utilities: pyfooda access, search index, paths, JSON helpers. |
| `delhaize.py` | Delhaize web scraper. |
| `carrefour.py` | Carrefour web scraper. |
| `colruyt.py` | Colruyt web scraper. |
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
