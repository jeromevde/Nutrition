# Skills

All pipeline logic lives under this package. This file is the consolidated map:
one section per skill, how to run it, where it fits, and whether we should keep
or deprecate it.

## Pipeline Summary

```text
Source ingest -> normalize -> initial mapping -> local remap loop -> report -> verify
```

Typical execution:

```bash
python -m skills.delhaize
python -m skills.source_normalizer data/delhaize --source delhaize --output data/purchases_normalized.csv
python -m skills.build_mapping
python -m skills.local_remap --top 900 --min-count 1 --apply --min-confidence high
python -m skills.nutrition_report
python -m skills.report_verifier
```

## common.py

Purpose:
- shared paths, batching/helpers, pyfooda compatibility accessors,
- JSON parsing helpers,
- semantic food index builder (`build_food_search_index`).

How used:
- imported by almost every skill.

Pipeline fit:
- foundation utilities.

Recommendation:
- Keep (core).

## source_normalizer.py

Purpose:
- normalize raw source CSVs into canonical schema:
	`product_name`, `price`, `barcode`, `date`, `source_file`, `source`.

How to run:

```bash
python -m skills.source_normalizer data/delhaize --source delhaize --output data/purchases_normalized.csv
```

Pipeline fit:
- canonicalization step before matching.

Recommendation:
- Keep.

## matcher.py

Purpose:
- semantic retrieval + external LLM decision for initial mapping.

How to run:

```bash
python -m skills.matcher data/delhaize --dry-run --output /tmp/matcher_candidates.csv --limit 25
python -m skills.matcher data/delhaize --output data/delhaize_mapping.csv
```

Pipeline fit:
- first-pass mapping bootstrap.

Recommendation:
- Keep, but optional when external LLM providers are unavailable.

## build_mapping.py

Purpose:
- orchestrate mapping build over tickets,
- merge prior mapping,
- enrich purchases,
- sanitize stale pyfooda keys.

How to run:

```bash
python -m skills.build_mapping
python -m skills.build_mapping --remap-from-verifier
```

Pipeline fit:
- main mapping orchestration.

Recommendation:
- Keep (core).

## local_remap.py

Purpose:
- local, provider-free iterative remap for highest-count unmatched names,
- multilingual normalization + concept anchors,
- embeddings-first retrieval (FAISS + sentence-transformers) with lexical fallback.

How to run:

```bash
python -m skills.local_remap --top 900 --min-count 1 --output data/local_remap_proposals.csv
python -m skills.local_remap --top 900 --min-count 1 --apply --min-confidence high
python -m skills.local_remap --top 900 --min-count 1 --no-semantic
```

Pipeline fit:
- fast iterative quality-improvement loop after initial mapping.

Recommendation:
- Keep (core). This is the default remap path when we want speed + no external LLM.

## nutrition_report.py

Purpose:
- compute per-trip and yearly metrics,
- scale nutrients to 2500 kcal reference,
- generate interactive HTML report.

How to run:

```bash
python -m skills.nutrition_report
```

Outputs:
- `data/nutrition_pertrip.csv`
- `data/nutrition_yearly.csv`
- `data/nutrition_report.html`

Pipeline fit:
- reporting/analytics output.

Recommendation:
- Keep (core).

## report_verifier.py

Purpose:
- offline report consistency/sanity checks,
- suspect contributor and mismatch detection.

How to run:

```bash
python -m skills.report_verifier
python -m skills.report_verifier --json
```

Pipeline fit:
- QA gate after report generation.

Recommendation:
- Keep.

## ocr.py

Purpose:
- OCR a single receipt image into canonical rows.

How to run:

```bash
python -m skills.ocr data/delhaize/2025_01_20.jpg --output-dir data/delhaize
```

Pipeline fit:
- source ingest for image receipts.

Recommendation:
- Keep if image OCR remains in scope.

## ocr_batch.py

Purpose:
- batch OCR over multiple receipt images.

How to run:

```bash
python -m skills.ocr_batch
```

Pipeline fit:
- bulk source ingest.

Recommendation:
- Keep if OCR is used; otherwise optional.

## delhaize.py

Purpose:
- source-specific Delhaize scraper/collector wrapper.

How to run:

```bash
python -m skills.delhaize
```

Pipeline fit:
- source ingest adapter.

Recommendation:
- Keep.

## carrefour.py

Purpose:
- source-specific Carrefour scraper/collector wrapper.

How to run:

```bash
python -m skills.carrefour
```

Pipeline fit:
- source ingest adapter.

Recommendation:
- Keep if Carrefour data still used; otherwise optional.

## colruyt.py

Purpose:
- source-specific Colruyt scraper/collector wrapper.

How to run:

```bash
python -m skills.colruyt
```

Pipeline fit:
- source ingest adapter.

Recommendation:
- Keep if Colruyt data still used; otherwise optional.

## observe.py

Purpose:
- lightweight observation/debug helper around source or pipeline runs.

How to run:

```bash
python -m skills.observe
```

Pipeline fit:
- developer diagnostics, not a required data step.

Recommendation:
- Keep but treat as utility.

## llm_client.py

Purpose:
- provider client factory for LLM-backed skills.

How used:
- imported by `matcher.py` and OCR skills.

Pipeline fit:
- infrastructure utility.

Recommendation:
- Keep (infrastructure).

## Consolidation Decision (Current)

Core set we definitely need:
- `common.py`, `source_normalizer.py`, `build_mapping.py`, `local_remap.py`, `nutrition_report.py`, `report_verifier.py`

Source adapters / ingest tools:
- `delhaize.py`, `carrefour.py`, `colruyt.py`, `ocr.py`, `ocr_batch.py`

Optional advanced branches:
- `matcher.py` (external LLM bootstrap)

Utility/infrastructure:
- `observe.py`, `llm_client.py`

No immediate deletions recommended yet; convert to optional usage rather than remove.
