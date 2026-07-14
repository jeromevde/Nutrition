"""Reusable LLM-assisted skills for the Nutrition pipeline.

The modules in this package are intentionally importable from scripts as well as
runnable from the command line with ``python -m skills.<module>``.
"""

__all__ = [
    "build_mapping",
    "carrefour",
    "colruyt",
    "common",
    "delhaize",
    "llm_client",
    "matcher",
    "nutrition_estimator",
    "nutrition_report",
    "observe",
    "ocr",
    "ocr_batch",
    "report_verifier",
    "source_normalizer",
]
