# Skills

Reusable LLM-assisted building blocks for the full nutrition pipeline. All Python
implementation code lives under this package; parsed data and generated reports
are under `data/`. Source-specific raw and parsed scraper artifacts live together
under `data/scrapers/<source>/`.

## Full Pipeline

```bash
python -m skills.scrapers.delhaize
python -m skills.ocr_batch
python -m skills.pipeline.build_mapping
python -m skills.pipeline.nutrition_report
python -m skills.report_verifier
```

Carrefour and Colruyt source scrapers:

```bash
python -m skills.scrapers.carrefour
python -m skills.scrapers.colruyt
```

## `matcher.py`

Semantic-search + LLM matcher for OCR or scraper product names.

```bash
python -m skills.matcher data/scrapers/delhaize --dry-run --output /tmp/matcher_candidates.csv --limit 25
python -m skills.matcher data/scrapers/delhaize --output data/delhaize_mapping.csv
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
python -m skills.ocr data/scrapers/delhaize/2025_01_20.jpg --output-dir data/scrapers/delhaize
```

It returns canonical OCR rows: `product_name`, `price`, `barcode`.

## `source_normalizer.py`

Canonicalizes supermarket exports into a common schema before matching.

```bash
python -m skills.source_normalizer data/scrapers/delhaize --source delhaize --output data/purchases_normalized.csv
```

Canonical columns:
`product_name`, `price`, `barcode`, `date`, `source_file`, `source`.

## Suggested Pipeline

```text
scraper/OCR -> source_normalizer -> matcher -> nutrition_report -> report_verifier -> targeted remap/fix
```

Use `python -m skills.<module>` for all executable Python entry points.
