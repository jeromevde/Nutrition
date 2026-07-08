"""LLM-assisted food matcher skill.

Reads OCR/product CSVs, retrieves pyfooda candidates with embedding search, and
asks an LLM to choose exact food matches plus package grams.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .common import (
    DEFAULT_MAPPING,
    DATA_DIR,
    DELHAIZE_SCRAPER_DIR,
    DEFAULT_MATCHER_MODEL,
    batched,
    build_food_search_index,
    llm_json,
    normalize_food_query,
)
from .llm_client import make_client

MATCHER_SYSTEM_PROMPT = """You are a nutrition database matching assistant.
You receive Belgian grocery receipt product names and candidate pyfooda food names.
For each item, choose the best exact candidate or mark it ignore.

Rules:
- pyfooda_name must be copied exactly from the candidates list.
- Use ignore for non-foods, malformed OCR, or when no candidate is close enough.
- Return grams for every match. Use explicit weights first; otherwise infer a conservative Belgian retail package size.
- Leading 4-digit years are not weights.
- Keep grams <= 5000 for one receipt line.

Return only a JSON array:
[{"id": 0, "action": "match", "pyfooda_name": "...", "grams": 250.0}, {"id": 1, "action": "ignore"}]
"""


@dataclass
class MatchResult:
    delhaize_name: str
    action: str
    pyfooda_name: str = ""
    llm_raw_name: str = ""
    grams: float | None = None
    candidates: list[str] | None = None

    def to_mapping_row(self) -> dict[str, Any]:
        return {
            "delhaize_name": self.delhaize_name,
            "action": self.action,
            "pyfooda_name": self.pyfooda_name,
            "llm_raw_name": self.llm_raw_name,
            "grams": self.grams,
        }


class MatcherSkill:
    """Batch product-name matcher backed by semantic search + LLM judgement."""

    def __init__(
        self,
        *,
        batch_size: int = 40,
        top_n: int = 10,
        model: str = DEFAULT_MATCHER_MODEL,
        dry_run: bool = False,
    ) -> None:
        self.batch_size = batch_size
        self.top_n = top_n
        self.model = model
        self.dry_run = dry_run
        self._client: Any | None = None
        self._resolved_model: str | None = None
        self._search_index = None

    @property
    def search_index(self):
        if self._search_index is None:
            self._search_index = build_food_search_index()
        return self._search_index

    @property
    def client_and_model(self) -> tuple[Any, str]:
        if self._client is None or self._resolved_model is None:
            self._client, self._resolved_model = make_client(self.model)
        return self._client, self._resolved_model

    def candidates_for(self, product_name: str) -> list[str]:
        query = normalize_food_query(product_name)
        try:
            return self.search_index.search(query, self.top_n)
        except ModuleNotFoundError:
            return self._lexical_candidates(query, self.top_n)

    @staticmethod
    def _lexical_candidates(query: str, top_n: int) -> list[str]:
        """Cheap fallback when FAISS/sentence-transformers are unavailable."""
        from pyfooda import api

        api.ensure_data_loaded()
        food_names = api.get_fooddata_df()["foodName"].dropna().drop_duplicates().astype(str)
        terms = [term for term in query.upper().split() if len(term) >= 3]
        if not terms:
            return []
        scored: list[tuple[int, str]] = []
        for food_name in food_names:
            upper = food_name.upper()
            score = sum(1 for term in terms if term in upper)
            if score:
                scored.append((score, food_name))
        scored.sort(key=lambda item: (-item[0], len(item[1]), item[1]))
        return [food_name for _, food_name in scored[:top_n]]

    def match_names(self, product_names: list[str], name_to_price: dict[str, float] | None = None) -> list[MatchResult]:
        indexed_names = list(enumerate(product_names))
        results: list[MatchResult] = []

        for chunk in batched(indexed_names, self.batch_size):
            items = []
            candidate_map: dict[int, list[str]] = {}
            for item_id, product_name in chunk:
                candidates = self.candidates_for(product_name)
                candidate_map[item_id] = candidates
                item: dict[str, Any] = {
                    "id": item_id,
                    "name": product_name,
                    "candidates": candidates,
                }
                if name_to_price and product_name in name_to_price:
                    item["price_eur"] = round(float(name_to_price[product_name]), 2)
                items.append(item)

            if self.dry_run:
                for item in items:
                    results.append(MatchResult(
                        delhaize_name=item["name"],
                        action="review",
                        candidates=item["candidates"],
                    ))
                continue

            client, model = self.client_and_model
            llm_rows = llm_json(client, model, MATCHER_SYSTEM_PROMPT, {"items": items})
            by_id = {int(row.get("id")): row for row in llm_rows if "id" in row}

            for item_id, product_name in chunk:
                raw = by_id.get(item_id, {"action": "ignore"})
                action = str(raw.get("action", "ignore")).lower()
                candidates = candidate_map[item_id]
                raw_name = str(raw.get("pyfooda_name", "")).strip()
                resolved_name = self._resolve_candidate(raw_name, candidates)
                grams = self._coerce_grams(raw.get("grams"))
                if action != "match" or not resolved_name:
                    results.append(MatchResult(product_name, "ignore", llm_raw_name=raw_name, candidates=candidates))
                else:
                    results.append(MatchResult(product_name, "match", resolved_name, raw_name, grams, candidates))
        return results

    @staticmethod
    def _resolve_candidate(raw_name: str, candidates: list[str]) -> str | None:
        if not raw_name:
            return None
        for candidate in candidates:
            if candidate == raw_name or candidate.upper() == raw_name.upper():
                return candidate
        return None

    @staticmethod
    def _coerce_grams(value: Any) -> float | None:
        if value is None or value == "":
            return None
        try:
            grams = float(value)
        except (TypeError, ValueError):
            return None
        if grams <= 0 or grams > 5000:
            return None
        return grams


def load_unique_products(paths: list[Path]) -> tuple[list[str], dict[str, float]]:
    frames = []
    product_columns = {"product_name", "name", "description", "item", "label"}
    generated_files = {
        "delhaize_mapping.csv",
        "nutrition_pertrip.csv",
        "nutrition_yearly.csv",
        "purchases_enriched.csv",
        "purchases_normalized.csv",
    }
    def _read_product_csv(path: Path) -> pd.DataFrame | None:
        if path.name in generated_files:
            return None
        try:
            data = pd.read_csv(path)
        except Exception:
            return None
        if not product_columns & set(data.columns):
            return None
        if "product_name" not in data.columns:
            for candidate in ("name", "description", "item", "label"):
                if candidate in data.columns:
                    data = data.rename(columns={candidate: "product_name"})
                    break
        return data

    for path in paths:
        if path.is_dir():
            for csv_path in sorted(path.glob("*.csv")):
                data = _read_product_csv(csv_path)
                if data is not None:
                    frames.append(data)
        else:
            data = _read_product_csv(path)
            if data is not None:
                frames.append(data)
    if not frames:
        return [], {}
    data = pd.concat(frames, ignore_index=True)
    data["product_name"] = data["product_name"].astype(str).str.strip().str.upper()
    names = sorted(name for name in data["product_name"].dropna().unique() if name)
    price_map: dict[str, float] = {}
    if "price" in data.columns:
        prices = pd.to_numeric(data["price"], errors="coerce")
        price_data = data.assign(price=prices).dropna(subset=["price"])
        price_map = price_data.groupby("product_name")["price"].median().to_dict()
    return names, price_map


def write_mapping(results: list[MatchResult], output_path: Path) -> None:
    rows = [result.to_mapping_row() for result in results if result.action in {"match", "ignore"}]
    pd.DataFrame(rows).to_csv(output_path, index=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="LLM match receipt product names to pyfooda foods")
    parser.add_argument("inputs", nargs="*", type=Path, default=[DELHAIZE_SCRAPER_DIR])
    parser.add_argument("--output", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument("--batch-size", type=int, default=40)
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true", help="write candidate previews without calling an LLM")
    args = parser.parse_args()

    product_names, price_map = load_unique_products(args.inputs)
    if args.limit:
        product_names = product_names[:args.limit]
    skill = MatcherSkill(batch_size=args.batch_size, top_n=args.top_n, dry_run=args.dry_run)
    results = skill.match_names(product_names, price_map)

    if args.dry_run:
        preview_rows = [
            {"product_name": result.delhaize_name, "candidates": " | ".join(result.candidates or [])}
            for result in results
        ]
        pd.DataFrame(preview_rows).to_csv(args.output, index=False)
    else:
        write_mapping(results, args.output)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
