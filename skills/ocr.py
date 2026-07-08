"""Receipt OCR skill.

Reusable vision-LLM OCR wrapper for supermarket receipts. It outputs normalized
rows that can be fed into source_normalizer and matcher.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import pandas as pd

from .common import DEFAULT_OCR_MODEL, image_to_data_url, parse_json_response
from .llm_client import make_client

OCR_SYSTEM_PROMPT = """You are a receipt OCR system for Belgian supermarket receipts.
Extract every purchased product line from the image.
Ignore totals, subtotals, payment lines, loyalty discounts, tax rows, and quantity-only rows.
Return only JSON:
[{"product_name":"...","price":1.23,"barcode":"..."}]
Use uppercase product names when visible. Use null for missing price or barcode.
"""


@dataclass
class OcrRow:
    product_name: str
    price: float | None = None
    barcode: str | None = None


class OcrSkill:
    """Run receipt-image OCR through the shared OpenAI-compatible LLM client."""

    def __init__(self, model: str = DEFAULT_OCR_MODEL) -> None:
        self.client, self.model = make_client(model)

    def extract_image(self, image_path: Path | str) -> list[OcrRow]:
        path = Path(image_path)
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": OCR_SYSTEM_PROMPT},
                    {"type": "image_url", "image_url": {"url": image_to_data_url(path)}},
                ],
            }],
            temperature=0,
            max_tokens=4096,
        )
        raw = response.choices[0].message.content or "[]"
        parsed = parse_json_response(raw)
        return [self._row_from_json(item) for item in parsed]

    @staticmethod
    def _row_from_json(item: dict[str, Any]) -> OcrRow:
        price = item.get("price")
        if isinstance(price, str):
            price = price.replace(",", ".")
            price = re.sub(r"[^0-9.-]", "", price)
        try:
            parsed_price = float(price) if price not in (None, "") else None
        except (TypeError, ValueError):
            parsed_price = None
        return OcrRow(
            product_name=str(item.get("product_name") or "").strip().upper(),
            price=parsed_price,
            barcode=str(item.get("barcode") or "").strip() or None,
        )


def write_rows(rows: list[OcrRow], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["product_name", "price", "barcode"])
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def main() -> None:
    parser = argparse.ArgumentParser(description="OCR receipt images with a vision LLM")
    parser.add_argument("images", nargs="+", type=Path)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--json", action="store_true", help="print JSON instead of writing CSVs")
    args = parser.parse_args()

    skill = OcrSkill()
    all_rows: dict[str, list[dict[str, Any]]] = {}
    for image in args.images:
        rows = skill.extract_image(image)
        all_rows[str(image)] = [asdict(row) for row in rows]
        if args.output_dir:
            write_rows(rows, args.output_dir / f"{image.stem}.csv")
    if args.json or not args.output_dir:
        print(json.dumps(all_rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
