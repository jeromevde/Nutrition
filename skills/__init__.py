"""Nutrition pipeline skills.

Pipeline (agent-centric):
  python -m skills.source_normalizer   # normalize raw CSVs
  python -m skills.agent_remap --generate  # see what's unmatched
  # agent fills data/agent_remap_responses.jsonl
  python -m skills.agent_remap --apply     # apply matches
  python -m skills.agent_remap --enrich    # re-enrich purchases (no new matches)
  python -m skills.nutrition_report        # build report
  python -m skills.delhaize / carrefour / colruyt  # scrapers
  python -m skills.ocr / ocr_batch         # OCR
"""

__all__ = [
    "agent_remap",
    "common",
    "delhaize",
    "carrefour",
    "colruyt",
    "llm_client",
    "nutrition_report",
    "observe",
    "ocr",
    "ocr_batch",
    "source_normalizer",
]
