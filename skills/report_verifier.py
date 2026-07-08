"""Nutrition report verifier skill.

Finds nutrient outliers, zero-contribution matches, and likely bad mappings in
the generated HTML report. This skill is intentionally offline-first so it can be
used as a cheap validation step after every report regeneration.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import pandas as pd

from .common import DEFAULT_REPORT, OUTPUT_DIR, load_report_data

_TOKEN_RE = re.compile(r"[A-Z]{3,}")
_STOPWORDS = {
    "BIO", "DLL", "DLH", "DLI", "DOL", "DELHAIZE", "GRAM", "GR", "G", "ML", "CL",
    "THE", "AND", "WITH", "RAW", "FRESH", "ORGANIC", "NATURE", "NATUREL", "D365",
}

_TOKEN_ALIASES = {
    "AVOCAT": "AVOCADO",
    "BEURRE": "BUTTER",
    "BOEUF": "BEEF",
    "BOUEF": "BEEF",
    "CAROTTE": "CARROT",
    "CAROTTES": "CARROT",
    "CARROTS": "CARROT",
    "CERISE": "CHERRY",
    "CHOCO": "CHOCOLATE",
    "CREME": "CREAM",
    "DINDE": "TURKEY",
    "HACHIS": "GROUND",
    "HUILE": "OIL",
    "JAMBON": "HAM",
    "LAIT": "MILK",
    "LAYS": "CHIPS",
    "MANGUE": "MANGO",
    "NOCCIOLAT": "HAZELNUT",
    "OEUFS": "EGG",
    "OEUFFS": "EGG",
    "OEUVS": "EGG",
    "OEUVFS": "EGG",
    "EGGS": "EGG",
    "PDT": "POTATO",
    "POTATOES": "POTATO",
    "POIREAU": "LEEK",
    "PORC": "PORK",
    "POULET": "CHICKEN",
    "PROSCIUTTO": "PROSCIUTTO",
    "RIZ": "RICE",
    "THON": "TUNA",
    "TOMATE": "TOMATO",
    "TOMATES": "TOMATO",
    "TORTELLO": "TORTELLONI",
    "TORTELLONI": "TORTELLONI",
    "VEAU": "VEAL",
}


def tokens(text: str) -> set[str]:
    result = set()
    for token in _TOKEN_RE.findall(str(text).upper()):
        if token in _STOPWORDS:
            continue
        result.add(_TOKEN_ALIASES.get(token, token))
    return result


def overlap_score(product_name: str, food_name: str) -> float:
    product_tokens = tokens(product_name)
    food_tokens = tokens(food_name)
    if not product_tokens or not food_tokens:
        return 0.0
    return len(product_tokens & food_tokens) / max(len(product_tokens), 1)


@dataclass
class Finding:
    kind: str
    severity: str
    title: str
    detail: str
    evidence: dict[str, Any]


class ReportVerifierSkill:
    """Audit a generated report for bad-match signals."""

    def __init__(self, report_path: Path | str = DEFAULT_REPORT, output_dir: Path | str = OUTPUT_DIR) -> None:
        self.report_path = Path(report_path)
        self.output_dir = Path(output_dir)
        self.data = load_report_data(self.report_path)

    def verify(self, *, low_pct: float = 50.0, high_pct: float = 120.0, top_share_pct: float = 1.0) -> dict[str, Any]:
        findings: list[Finding] = []
        outlier_nutrients = self._nutrient_outliers(low_pct, high_pct)
        findings.extend(self._zero_nutrient_findings())
        findings.extend(self._mapping_findings(outlier_nutrients, top_share_pct))
        findings.extend(self._outlier_trip_findings())
        return {
            "report_path": str(self.report_path),
            "nutrient_outliers": outlier_nutrients,
            "findings": [asdict(finding) for finding in findings],
        }

    def _nutrient_outliers(self, low_pct: float, high_pct: float) -> list[dict[str, Any]]:
        nutrients = self.data.get("nutrients", {}).get("all", {})
        outliers = []
        for nutrient, row in nutrients.items():
            pct = row.get("pct")
            if pct is None:
                continue
            if pct < low_pct or pct > high_pct:
                outliers.append({
                    "nutrient": nutrient,
                    "pct_drv": pct,
                    "value": row.get("value"),
                    "unit": row.get("unit"),
                    "direction": "high" if pct > high_pct else "low",
                })
        return outliers

    def _zero_nutrient_findings(self) -> list[Finding]:
        grouped: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "grams": 0.0, "products": Counter()})
        for row in self.data.get("purchases", {}).get("all", []):
            if not row.get("matched") or row.get("item_nutrients"):
                continue
            food = row.get("pyfooda_name", "")
            grouped[food]["count"] += 1
            grouped[food]["grams"] += float(row.get("grams") or 0)
            grouped[food]["products"][row.get("product_name", "")] += 1

        findings = []
        for food, info in sorted(grouped.items(), key=lambda item: item[1]["count"], reverse=True):
            examples = dict(info["products"].most_common(6))
            findings.append(Finding(
                kind="zero_nutrients",
                severity="high" if info["count"] >= 2 else "medium",
                title=f"Matched food has no nutrient payload: {food}",
                detail="The report matched receipt rows to this food, but item_nutrients is empty. This usually means the pyfooda name is not an exact database key.",
                evidence={"count": info["count"], "grams": round(info["grams"], 1), "examples": examples},
            ))
        return findings

    def _mapping_findings(self, outlier_nutrients: list[dict[str, Any]], top_share_pct: float) -> list[Finding]:
        purchases = self.data.get("purchases", {}).get("all", [])
        by_food: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in purchases:
            if row.get("matched"):
                by_food[row.get("pyfooda_name", "")].append(row)

        findings: list[Finding] = []
        top_foods = self.data.get("nutrient_top_foods", {}).get("all", {})
        for nutrient_row in outlier_nutrients:
            if nutrient_row["direction"] != "high":
                continue
            nutrient = nutrient_row["nutrient"]
            for entry in top_foods.get(nutrient, []):
                if entry.get("pct_of_total", 0) < top_share_pct:
                    continue
                food = entry.get("food", "")
                product_rows = by_food.get(food, [])
                product_counter = Counter(row.get("product_name", "") for row in product_rows)
                examples = dict(product_counter.most_common(5))
                scores = [overlap_score(product, food) for product in product_counter]
                avg_score = sum(scores) / len(scores) if scores else 0.0
                red_flag = self._red_flag(food, product_counter)
                if avg_score < 0.15 or red_flag:
                    findings.append(Finding(
                        kind="suspect_mapping",
                        severity="high" if entry.get("pct_of_total", 0) >= 3 else "medium",
                        title=f"Suspicious top contributor for {nutrient}: {food}",
                        detail=red_flag or "Receipt-name tokens barely overlap the matched food name; review the mapping before trusting this nutrient outlier.",
                        evidence={
                            "nutrient": nutrient,
                            "pct_of_total": entry.get("pct_of_total"),
                            "amount": entry.get("amount"),
                            "count": len(product_rows),
                            "avg_token_overlap": round(avg_score, 3),
                            "examples": examples,
                        },
                    ))
        return findings

    @staticmethod
    def _red_flag(food: str, product_counter: Counter[str]) -> str | None:
        products = " ".join(product_counter.keys()).upper()
        food_upper = food.upper()
        if "POTATO" in food_upper and "MINT" in products:
            return "Mint/grenaille OCR label is mixed into a potato mapping; verify this is not herbs or chilies."
        if "SAUCE" in food_upper and any(word in products for word in ("TORTEL", "TORRICO", "TOGRELLO")):
            return "Tortelloni/tortello OCR labels were matched to sauce."
        if "BRUSCHETTA" in food_upper and "TOMATE" in products:
            return "Fresh tomato labels were matched to prepared bruschetta."
        if "STUFFED" in food_upper and "POULET" in products:
            return "Plain chicken labels were matched to a stuffed prepared chicken product."
        if "SPREAD" in food_upper and "HUILE" in products:
            return "Cooking oil labels were matched to a salted spread."
        return None

    def _outlier_trip_findings(self) -> list[Finding]:
        trips_path = self.output_dir / "nutrition_pertrip.csv"
        if not trips_path.exists():
            return []
        trips = pd.read_csv(trips_path)
        if "is_outlier" not in trips.columns:
            return []
        outliers = trips[trips["is_outlier"].astype(str).str.lower().eq("true")]
        findings = []
        for _, row in outliers.iterrows():
            findings.append(Finding(
                kind="outlier_trip",
                severity="medium",
                title=f"Outlier trip excluded from yearly averages: {row.get('source_file')}",
                detail="Inspect this trip for tiny-basket scaling, zero-energy foods, or one bad high-density match.",
                evidence={
                    "date": str(row.get("date")),
                    "energy": row.get("Energy"),
                    "sodium": row.get("Sodium"),
                    "total_fat": row.get("Total fat"),
                    "saturated_fat": row.get("Fatty acids, total saturated"),
                },
            ))
        return findings


def format_markdown(result: dict[str, Any]) -> str:
    lines = [f"# Report verifier: {result['report_path']}", ""]
    lines.append("## Nutrient outliers")
    for row in result["nutrient_outliers"]:
        lines.append(f"- {row['nutrient']}: {row['pct_drv']}% DRV ({row['direction']})")
    if not result["nutrient_outliers"]:
        lines.append("- None")
    lines.append("")
    lines.append("## Findings")
    for finding in result["findings"]:
        lines.append(f"- [{finding['severity']}] {finding['title']}")
        lines.append(f"  {finding['detail']}")
        lines.append(f"  Evidence: {json.dumps(finding['evidence'], ensure_ascii=False)}")
    if not result["findings"]:
        lines.append("- None")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify generated nutrition report for bad-match signals")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--json", action="store_true", help="print raw JSON instead of markdown")
    parser.add_argument("--low-pct", type=float, default=50.0)
    parser.add_argument("--high-pct", type=float, default=120.0)
    parser.add_argument("--top-share-pct", type=float, default=1.0)
    args = parser.parse_args()

    result = ReportVerifierSkill(args.report).verify(
        low_pct=args.low_pct,
        high_pct=args.high_pct,
        top_share_pct=args.top_share_pct,
    )
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(format_markdown(result))


if __name__ == "__main__":
    main()
