"""Agent-driven remap skill.

The pipeline is intentionally LLM-centric: instead of complex deterministic
heuristics, unmatched items are sent to the coding agent (Copilot / Claude)
which has food knowledge, multilingual understanding, and price-based quantity
inference baked in.

Workflow
--------
1. Generate a request file of unmatched items:
       python -m skills.agent_remap --generate

   This writes `data/agent_remap_requests.jsonl` (one item per line).

2. The agent (or a human) reads the file and responds with a JSONL of matches:
       data/agent_remap_responses.jsonl
   Each line: {"product_name": "...", "pyfooda_name": "...", "grams": <float|null>}
   Or to mark as non-food/ignore: {"product_name": "...", "action": "ignore"}

3. Apply responses:
       python -m skills.agent_remap --apply

4. Regenerate the report:
       python -m skills.nutrition_report
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .common import DEFAULT_MAPPING, DEFAULT_PURCHASES, OUTPUT_DIR, get_pyfooda_foods_df

DEFAULT_REQUESTS = OUTPUT_DIR / "agent_remap_requests.jsonl"
DEFAULT_RESPONSES = OUTPUT_DIR / "agent_remap_responses.jsonl"


def generate_requests(
    purchases_csv: Path,
    out_path: Path,
    min_count: int = 2,
) -> int:
    """Write unmatched items (count >= min_count) to a JSONL request file."""
    df = pd.read_csv(purchases_csv, dtype=str)
    foods = set(get_pyfooda_foods_df()["display_name"].dropna().astype(str))

    df["product_name"] = df["product_name"].fillna("").str.upper()
    df["price"] = pd.to_numeric(df["price"], errors="coerce")

    valid = (df["llm_action"].fillna("").str.lower().eq("match")) & (
        df["pyfooda_name"].fillna("").isin(foods)
    )
    unmatched = df[~valid].copy()

    grp = (
        unmatched.groupby("product_name")
        .agg(count=("product_name", "size"), median_price=("price", "median"))
        .reset_index()
        .sort_values("count", ascending=False)
    )
    grp = grp[grp["count"] >= min_count].reset_index(drop=True)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        for _, row in grp.iterrows():
            fh.write(
                json.dumps(
                    {
                        "product_name": row["product_name"],
                        "count": int(row["count"]),
                        "median_price_eur": None if pd.isna(row["median_price"]) else round(float(row["median_price"]), 2),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    print(f"Wrote {len(grp)} requests to {out_path}")
    return len(grp)


def apply_responses(
    mapping_csv: Path,
    purchases_csv: Path,
    responses_path: Path,
) -> tuple[int, int]:
    """Read agent responses and apply them to mapping + purchases."""
    foods = set(get_pyfooda_foods_df()["display_name"].dropna().astype(str))

    responses: list[dict] = []
    with responses_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                responses.append(json.loads(line))

    mapping = pd.read_csv(mapping_csv, dtype=str)
    mapping["delhaize_name"] = mapping["delhaize_name"].fillna("").str.upper()

    applied = ignored = 0
    for resp in responses:
        name = str(resp.get("product_name", "")).upper()
        action = str(resp.get("action", "match")).lower()
        pyfooda_name = str(resp.get("pyfooda_name", "")).strip()
        grams = resp.get("grams")

        if action == "ignore" or not name:
            # Explicit ignore
            mask = mapping["delhaize_name"] == name
            if mask.any():
                mapping.loc[mask, "action"] = "ignore"
                mapping.loc[mask, "pyfooda_name"] = ""
                mapping.loc[mask, "grams"] = ""
            else:
                mapping.loc[len(mapping)] = {
                    "delhaize_name": name, "action": "ignore",
                    "pyfooda_name": "", "llm_raw_name": "", "grams": "",
                }
            ignored += 1
            continue

        if not pyfooda_name or pyfooda_name not in foods:
            # Skip invalid keys silently — guard keeps data clean
            continue

        mask = mapping["delhaize_name"] == name
        row_data = {
            "action": "match",
            "pyfooda_name": pyfooda_name,
            "llm_raw_name": pyfooda_name,
            "grams": "" if grams is None else str(grams),
        }
        if mask.any():
            for col, val in row_data.items():
                mapping.loc[mask, col] = val
        else:
            mapping.loc[len(mapping)] = {"delhaize_name": name, **row_data}
        applied += 1

    mapping = mapping.drop_duplicates(subset=["delhaize_name"], keep="last").reset_index(drop=True)
    mapping.to_csv(mapping_csv, index=False)

    # Re-enrich purchases
    purchases = pd.read_csv(purchases_csv, dtype=str)
    purchases["product_name"] = purchases["product_name"].fillna("").str.upper()
    lookup = mapping.set_index("delhaize_name")[["action", "pyfooda_name", "grams"]].to_dict("index")
    purchases["llm_action"] = purchases["product_name"].map(lambda n: lookup.get(n, {}).get("action", "ignore"))
    purchases["pyfooda_name"] = purchases["product_name"].map(lambda n: lookup.get(n, {}).get("pyfooda_name", ""))
    purchases["grams_in_name"] = purchases["product_name"].map(lambda n: lookup.get(n, {}).get("grams", ""))

    # Final guard
    bad = (purchases["llm_action"].fillna("").str.lower() == "match") & (
        ~purchases["pyfooda_name"].fillna("").isin(foods)
    )
    purchases.loc[bad, "llm_action"] = "ignore"
    purchases.loc[bad, "pyfooda_name"] = ""
    purchases.loc[bad, "grams_in_name"] = ""
    purchases.to_csv(purchases_csv, index=False)

    matched = int((purchases["llm_action"].fillna("").str.lower() == "match").sum())
    print(f"Applied {applied} matches, {ignored} ignores → {matched} total matched purchase rows")
    return applied, matched


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent-driven remap for unmatched items")
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--purchases", type=Path, default=DEFAULT_PURCHASES)
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument("--requests", type=Path, default=DEFAULT_REQUESTS)
    parser.add_argument("--responses", type=Path, default=DEFAULT_RESPONSES)
    parser.add_argument("--min-count", type=int, default=2)
    args = parser.parse_args()

    if args.generate:
        generate_requests(args.purchases, args.requests, min_count=args.min_count)
    elif args.apply:
        apply_responses(args.mapping, args.purchases, args.responses)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
