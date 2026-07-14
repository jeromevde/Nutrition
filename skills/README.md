# Skills

Reusable LLM-assisted building blocks for the full nutrition pipeline. All Python
implementation code lives under this package; parsed data and generated reports
are under `data/`. Source-specific raw and parsed scraper artifacts live together
under `data/<source>/`.

## Full Pipeline

```bash
python -m skills.delhaize
python -m skills.ocr_batch
python -m skills.build_mapping
python -m skills.nutrition_estimator --backend agent --limit 25
python -m skills.nutrition_report
python -m skills.report_verifier
```

Carrefour and Colruyt source scrapers:

```bash
python -m skills.carrefour
python -m skills.colruyt
```

## `matcher.py`

Semantic-search + LLM matcher for OCR or scraper product names.

```bash
python -m skills.matcher data/delhaize --dry-run --output /tmp/matcher_candidates.csv --limit 25
python -m skills.matcher data/delhaize --output data/delhaize_mapping.csv
```

What it does:
- reads product CSVs or folders of CSVs;
- builds a FAISS index over pyfooda food names;
- retrieves top candidates per product name;
- asks the LLM to choose an exact pyfooda match and package grams;
- writes mapping rows compatible with the existing nutrition report.

## `report_verifier.py`

Offline verifier for generated `nutrition_report.html`.

```bash
python -m skills.report_verifier
python -m skills.report_verifier --json
```

Checks:
- nutrients far outside reference ranges;
- high-impact top contributors with suspicious product/name overlap;
- matched foods with empty nutrient payloads;
- outlier trips excluded from yearly averages.

## `ocr.py`

Vision-LLM receipt OCR wrapper.

```bash
python -m skills.ocr data/delhaize/2025_01_20.jpg --output-dir data/delhaize
```

It returns canonical OCR rows: `product_name`, `price`, `barcode`.

## `nutrition_estimator.py`

LLM-estimates complete per-100g nutrition profiles for receipt items when pyfooda
is sparse or suspicious. The prompt explicitly requests every nutrient used by
the report and every output carries confidence, source, and min/max range.

Agent backend, for using this coding agent/manual Copilot flow:

```bash
python -m skills.nutrition_estimator --backend agent --limit 25
```

This writes:

- `data/nutrition_estimator_agent_requests.jsonl`
- `data/nutrition_estimator_agent_prompt.md`

After an agent or human writes response JSON/JSONL, import it:

```bash
python -m skills.nutrition_estimator --backend agent --agent-response data/nutrition_estimator_agent_responses.jsonl --output data/nutrition_estimates.csv
```

OpenRouter backend:

```bash
export OPENROUTER_API_KEY="..."
python -m skills.nutrition_estimator --backend openrouter --model google/gemini-2.0-flash-001 --limit 25
```

Hugging Face Inference Providers backend:

```bash
export HF_TOKEN="..."
python -m skills.nutrition_estimator --backend huggingface --model Qwen/Qwen2.5-72B-Instruct --limit 25
```

Default output: `data/nutrition_estimates.csv`.

## `source_normalizer.py`

Canonicalizes supermarket exports into a common schema before matching.

```bash
python -m skills.source_normalizer data/delhaize --source delhaize --output data/purchases_normalized.csv
```

Canonical columns:
`product_name`, `price`, `barcode`, `date`, `source_file`, `source`.

## Suggested Pipeline

```text
scraper/OCR -> source_normalizer -> matcher -> nutrition_report -> report_verifier -> targeted remap/fix
```

Use `python -m skills.<module>` for all executable Python entry points.
