"""LLM nutrition estimator skill.

This skill estimates a full per-100g nutrition profile from receipt item context.
It is intended to complement sparse or suspicious pyfooda data, not to silently
replace measured nutrition. Every output row carries source, confidence, and
range information.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import openai
import pandas as pd

from .common import DATA_DIR, DEFAULT_PURCHASES, batched, parse_json_response
from .llm_client import OPENROUTER_BASE_URL

NUTRIENTS: list[dict[str, str]] = [
    {"name": "Energy", "unit": "KCAL"},
    {"name": "Protein", "unit": "G"},
    {"name": "Carbohydrate", "unit": "G"},
    {"name": "Fiber", "unit": "G"},
    {"name": "Sugars, Total", "unit": "G"},
    {"name": "Total fat", "unit": "G"},
    {"name": "Fatty acids, total saturated", "unit": "G"},
    {"name": "Cholesterol", "unit": "MG"},
    {"name": "Calcium", "unit": "MG"},
    {"name": "Iron", "unit": "MG"},
    {"name": "Magnesium", "unit": "MG"},
    {"name": "Potassium", "unit": "MG"},
    {"name": "Sodium", "unit": "MG"},
    {"name": "Zinc", "unit": "MG"},
    {"name": "Vitamin A, RAE", "unit": "UG"},
    {"name": "Vitamin C", "unit": "MG"},
    {"name": "Vitamin D (D2 + D3)", "unit": "UG"},
    {"name": "Vitamin B-12", "unit": "UG"},
    {"name": "Folate, total", "unit": "UG"},
    {"name": "Thiamin", "unit": "MG"},
    {"name": "Riboflavin", "unit": "MG"},
]
NUTRIENT_NAMES = [row["name"] for row in NUTRIENTS]

DEFAULT_OPENROUTER_MODEL = "google/gemini-2.0-flash-001"
DEFAULT_HUGGINGFACE_MODEL = "Qwen/Qwen2.5-72B-Instruct"
HUGGINGFACE_OPENAI_BASE_URL = "https://router.huggingface.co/v1"

ESTIMATOR_SYSTEM_PROMPT = """You are a cautious nutrition estimation system.

Task:
Estimate a plausible nutrition profile PER 100 GRAMS for Belgian grocery receipt items.
You must explicitly answer every nutrient in the requested nutrient list, using the exact nutrient names and units provided.

Important rules:
- Return JSON only, no markdown.
- Do not pretend exact precision. Give expected value plus plausible min/max range.
- Use null for a nutrient only if no defensible estimate is possible.
- Prefer typical Belgian/EU retail product composition over US branded oddities.
- Use product name, store/source context, grams, price, current pyfooda match, and current pyfooda nutrients.
- If pyfooda looks sparse, impossible, or too brand-specific, estimate from the generic food category.
- Confidence must be one of: high, medium, low.
- source must be one of: pyfooda_confirmed, llm_estimate, llm_gap_fill, uncertain.
- Micronutrients should usually be medium/low confidence unless the food is a standard whole food.
- Sodium in prepared foods is highly variable; use wider ranges.
- If the item is non-food or impossible OCR, set canonical_food_name to null and every nutrient value to null.

Response schema:
[
  {
    "id": 0,
    "canonical_food_name": "typical food/category or null",
    "overall_confidence": "high|medium|low",
    "notes": "short reason and major uncertainty",
    "nutrients": {
      "Energy": {"unit":"KCAL", "value_per_100g": 0, "min_per_100g": 0, "max_per_100g": 0, "confidence":"high|medium|low", "source":"pyfooda_confirmed|llm_estimate|llm_gap_fill|uncertain"},
      "Protein": {"unit":"G", "value_per_100g": 0, "min_per_100g": 0, "max_per_100g": 0, "confidence":"high|medium|low", "source":"pyfooda_confirmed|llm_estimate|llm_gap_fill|uncertain"}
    }
  }
]
"""


@dataclass
class EstimateItem:
    id: int
    product_name: str
    current_pyfooda_name: str
    grams: float | None
    count: int
    median_price_eur: float | None
    source_files: list[str]
    current_pyfooda_nutrients: dict[str, dict[str, Any]]

    def to_prompt_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "product_name": self.product_name,
            "store_context": "Belgian supermarket receipt, mostly Delhaize unless source file says otherwise",
            "current_pyfooda_name": self.current_pyfooda_name or None,
            "grams_per_purchase": self.grams,
            "purchase_count": self.count,
            "median_price_eur": self.median_price_eur,
            "source_files_sample": self.source_files[:5],
            "current_pyfooda_nutrients_per_100g": self.current_pyfooda_nutrients,
        }


class NutritionEstimatorSkill:
    """Build LLM nutrition-estimation batches and write estimate CSVs."""

    def __init__(
        self,
        *,
        purchases_path: Path = DEFAULT_PURCHASES,
        mode: str = "gaps",
        include_unmatched: bool = False,
    ) -> None:
        self.purchases_path = purchases_path
        self.mode = mode
        self.include_unmatched = include_unmatched
        self._foods_df: pd.DataFrame | None = None

    @property
    def foods_df(self) -> pd.DataFrame:
        if self._foods_df is None:
            from pyfooda import api

            api.ensure_data_loaded()
            fooddata = api.get_fooddata_df().copy()
            priority = {
                "foundation_food": 0,
                "sr_legacy_food": 1,
                "survey_fndds_food": 2,
                "sub_sample_food": 3,
                "agricultural_acquisition": 4,
                "branded_food": 5,
            }
            fooddata["_prio"] = fooddata["data_type"].map(priority).fillna(99)
            self._foods_df = (
                fooddata.sort_values(["foodName", "_prio"])
                .drop_duplicates("foodName", keep="first")
                .set_index("foodName")
            )
        return self._foods_df

    def load_items(self, *, limit: int | None = None) -> list[EstimateItem]:
        purchases = pd.read_csv(self.purchases_path)
        if not self.include_unmatched and "llm_action" in purchases.columns:
            purchases = purchases[purchases["llm_action"].eq("match")].copy()

        purchases["product_name"] = purchases["product_name"].astype(str).str.strip().str.upper()
        purchases["pyfooda_name"] = purchases.get("pyfooda_name", "").fillna("").astype(str)
        purchases["grams_in_name"] = pd.to_numeric(purchases.get("grams_in_name"), errors="coerce")
        purchases["price"] = pd.to_numeric(purchases.get("price"), errors="coerce")

        group_cols = ["product_name", "pyfooda_name", "grams_in_name"]
        grouped = purchases.groupby(group_cols, dropna=False)
        items: list[EstimateItem] = []
        for item_id, (key, group) in enumerate(grouped):
            product_name, pyfooda_name, grams = key
            current = self._pyfooda_profile(pyfooda_name)
            if self.mode == "gaps" and current and all(name in current for name in NUTRIENT_NAMES):
                continue
            median_price = group["price"].median()
            source_files = sorted(str(v) for v in group.get("source_file", pd.Series(dtype=str)).dropna().unique())
            items.append(EstimateItem(
                id=len(items),
                product_name=str(product_name),
                current_pyfooda_name=str(pyfooda_name) if pyfooda_name == pyfooda_name else "",
                grams=float(grams) if grams == grams else None,
                count=int(len(group)),
                median_price_eur=float(median_price) if median_price == median_price else None,
                source_files=source_files,
                current_pyfooda_nutrients=current,
            ))
            if limit is not None and len(items) >= limit:
                break
        return items

    def _pyfooda_profile(self, pyfooda_name: str) -> dict[str, dict[str, Any]]:
        if not pyfooda_name or pyfooda_name not in self.foods_df.index:
            return {}
        row = self.foods_df.loc[pyfooda_name]
        profile: dict[str, dict[str, Any]] = {}
        for nutrient in NUTRIENTS:
            name = nutrient["name"]
            if name in row.index and pd.notna(row[name]):
                profile[name] = {
                    "unit": nutrient["unit"],
                    "value_per_100g": round(float(row[name]), 4),
                }
        return profile

    def build_payloads(self, items: list[EstimateItem], batch_size: int) -> list[dict[str, Any]]:
        payloads = []
        for chunk in batched(items, batch_size):
            payloads.append({
                "nutrients_requested_exactly": NUTRIENTS,
                "items": [item.to_prompt_dict() for item in chunk],
            })
        return payloads

    def write_agent_requests(self, payloads: list[dict[str, Any]], request_out: Path, prompt_out: Path) -> None:
        request_out.parent.mkdir(parents=True, exist_ok=True)
        with request_out.open("w", encoding="utf-8") as handle:
            for payload in payloads:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        prompt_out.write_text(
            ESTIMATOR_SYSTEM_PROMPT
            + "\n\nRead each JSONL line in `"
            + str(request_out)
            + "`, respond with one JSON array per line using the schema above. Save responses as JSONL.\n",
            encoding="utf-8",
        )

    def estimate_with_openai_compatible(
        self,
        payloads: list[dict[str, Any]],
        *,
        base_url: str,
        api_key: str,
        model: str,
        max_tokens: int = 8192,
    ) -> list[dict[str, Any]]:
        client = openai.OpenAI(base_url=base_url, api_key=api_key, timeout=180, max_retries=2)
        all_rows: list[dict[str, Any]] = []
        for payload in payloads:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": ESTIMATOR_SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                temperature=0.1,
                max_tokens=max_tokens,
            )
            parsed = parse_json_response(response.choices[0].message.content or "[]")
            if not isinstance(parsed, list):
                raise ValueError("Estimator response must be a JSON array")
            all_rows.extend(parsed)
        return all_rows

    @staticmethod
    def read_agent_response(path: Path) -> list[dict[str, Any]]:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return []
        rows: list[dict[str, Any]] = []
        if text.startswith("["):
            parsed = parse_json_response(text)
            if not isinstance(parsed, list):
                raise ValueError("Agent response JSON must be an array")
            return parsed
        for line in text.splitlines():
            if not line.strip():
                continue
            parsed = parse_json_response(line)
            if isinstance(parsed, list):
                rows.extend(parsed)
            else:
                rows.append(parsed)
        return rows


def flatten_estimates(raw_estimates: list[dict[str, Any]], output_path: Path) -> None:
    rows: list[dict[str, Any]] = []
    for estimate in raw_estimates:
        nutrients = estimate.get("nutrients") or {}
        for nutrient in NUTRIENTS:
            name = nutrient["name"]
            data = nutrients.get(name) or {}
            rows.append({
                "item_id": estimate.get("id"),
                "canonical_food_name": estimate.get("canonical_food_name"),
                "overall_confidence": estimate.get("overall_confidence"),
                "notes": estimate.get("notes"),
                "nutrient": name,
                "unit": data.get("unit", nutrient["unit"]),
                "value_per_100g": data.get("value_per_100g"),
                "min_per_100g": data.get("min_per_100g"),
                "max_per_100g": data.get("max_per_100g"),
                "confidence": data.get("confidence"),
                "source": data.get("source"),
            })
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(output_path, index=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Estimate full nutrition profiles with LLM backends")
    parser.add_argument("--backend", choices=["agent", "openrouter", "huggingface"], default="agent")
    parser.add_argument("--input", type=Path, default=DEFAULT_PURCHASES)
    parser.add_argument("--output", type=Path, default=DATA_DIR / "nutrition_estimates.csv")
    parser.add_argument("--mode", choices=["gaps", "all"], default="gaps")
    parser.add_argument("--include-unmatched", action="store_true")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--agent-request-out", type=Path, default=DATA_DIR / "nutrition_estimator_agent_requests.jsonl")
    parser.add_argument("--agent-prompt-out", type=Path, default=DATA_DIR / "nutrition_estimator_agent_prompt.md")
    parser.add_argument("--agent-response", type=Path, default=None)
    args = parser.parse_args()

    skill = NutritionEstimatorSkill(
        purchases_path=args.input,
        mode=args.mode,
        include_unmatched=args.include_unmatched,
    )
    items = skill.load_items(limit=args.limit)
    payloads = skill.build_payloads(items, args.batch_size)

    if args.backend == "agent":
        skill.write_agent_requests(payloads, args.agent_request_out, args.agent_prompt_out)
        print(f"Wrote agent requests: {args.agent_request_out}")
        print(f"Wrote agent prompt:   {args.agent_prompt_out}")
        if args.agent_response:
            estimates = skill.read_agent_response(args.agent_response)
            flatten_estimates(estimates, args.output)
            print(f"Wrote estimates:      {args.output}")
        return

    if args.backend == "openrouter":
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise SystemExit("OPENROUTER_API_KEY is required for --backend openrouter")
        estimates = skill.estimate_with_openai_compatible(
            payloads,
            base_url=OPENROUTER_BASE_URL,
            api_key=api_key,
            model=args.model or DEFAULT_OPENROUTER_MODEL,
        )
    else:
        api_key = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACEHUB_API_TOKEN")
        if not api_key:
            raise SystemExit("HF_TOKEN or HUGGINGFACEHUB_API_TOKEN is required for --backend huggingface")
        estimates = skill.estimate_with_openai_compatible(
            payloads,
            base_url=HUGGINGFACE_OPENAI_BASE_URL,
            api_key=api_key,
            model=args.model or DEFAULT_HUGGINGFACE_MODEL,
        )

    flatten_estimates(estimates, args.output)
    print(f"Wrote estimates: {args.output}")


if __name__ == "__main__":
    main()
