"""AI summary injection skill.

Usage:
    python -m skills.ai_summary          # injects data/ai_summary.html into report
    python -m skills.ai_summary --check  # just verifies file exists
"""
from __future__ import annotations
import argparse
import re
from pathlib import Path
from .common import OUTPUT_DIR

SUMMARY_HTML = OUTPUT_DIR / "ai_summary.html"
REPORT_HTML  = OUTPUT_DIR / "nutrition_report.html"

_ANCHOR = '<div class="wrap">'
_MARKER_START = '<!-- ai-summary-start -->'
_MARKER_END   = '<!-- ai-summary-end -->'


def inject(report_path: Path = REPORT_HTML, summary_path: Path = SUMMARY_HTML) -> None:
    if not summary_path.exists():
        print(f"No summary found at {summary_path} — skipping injection")
        return
    if not report_path.exists():
        print(f"Report not found at {report_path}")
        return

    summary_html = summary_path.read_text(encoding="utf-8")
    report = report_path.read_text(encoding="utf-8")

    # Remove any prior injection
    report = re.sub(
        rf"{re.escape(_MARKER_START)}.*?{re.escape(_MARKER_END)}",
        "",
        report,
        flags=re.DOTALL,
    )

    block = f"{_MARKER_START}\n{summary_html}\n{_MARKER_END}\n"
    if _ANCHOR in report:
        report = report.replace(_ANCHOR, _ANCHOR + "\n" + block, 1)
    else:
        report = block + report

    report_path.write_text(report, encoding="utf-8")
    print(f"AI summary injected into {report_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Inject AI summary into nutrition report")
    parser.add_argument("--report",  type=Path, default=REPORT_HTML)
    parser.add_argument("--summary", type=Path, default=SUMMARY_HTML)
    parser.add_argument("--check",   action="store_true")
    args = parser.parse_args()
    if args.check:
        print("Summary exists:", args.summary.exists())
    else:
        inject(args.report, args.summary)


if __name__ == "__main__":
    main()
