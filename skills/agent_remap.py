"""Agent-driven remap — the single matching entry point.

Pipeline
--------
   python -m skills.agent_remap --generate      # see what's unmatched
   # agent reads data/agent_remap_requests.jsonl and writes data/agent_remap_responses.jsonl
   python -m skills.agent_remap --apply         # apply matches + sanitize stale keys
   python -m skills.agent_remap --enrich        # re-enrich purchases from mapping only
   python -m skills.nutrition_report            # build report

Response format (one JSON per line):
   {"product_name": "APPEL PINK LADY 6P", "pyfooda_name": "APPLE", "grams": 900}
   {"product_name": "ORAL B", "action": "ignore"}

grams rules for agent:
- Use explicit weight from label first (e.g. "250G" → 250)
- Infer from piece count × typical unit weight:
    apple/pear ~150g, banana ~120g, orange ~200g, lemon ~100g, avocado ~170g,
    egg ~60g, onion ~150g, pepper/bell pepper ~150g
- Infer from price when both weight and count are unknown:
    butter €2/250g €3/500g · salmon €4/150g €8/300g · chicken breast €5/300g
- If truly unknown, omit grams (null) — report will use 100g default
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd

from .common import DEFAULT_MAPPING, DEFAULT_PURCHASES, OUTPUT_DIR, get_pyfooda_foods_df

DEFAULT_REQUESTS = OUTPUT_DIR / "agent_remap_requests.jsonl"
DEFAULT_RESPONSES = OUTPUT_DIR / "agent_remap_responses.jsonl"

# Typical unit weight (grams) for common piece-sold items.
_UNIT_WEIGHTS: dict[str, int] = {
    "APPLE": 150, "POMME": 150,
    "PEAR": 170, "POIRE": 170,
    "BANANA": 120, "BANANE": 120,
    "ORANGE": 200,
    "LEMON": 100, "CITRON": 100,
    "AVOCADO": 170, "AVOCAT": 170,
    "EGG": 60, "OEUF": 60,
    "ONION": 150, "OIGNON": 150,
    "PEPPER": 150, "POIVRON": 150,
    "KIWI": 80,
    "LIME": 70,
}

_PIECE_RE = re.compile(r"\b(\d+)\s*[Xx]?\s*[Pp][Cc]?[Ss]?\b|\b(\d+)\s*[Xx]\s*\d|\b(\d+)\s*STUKS\b", re.I)


def _extract_weight_hint(product_name: str) -> str | None:
    """Return a human-readable weight hint string for the agent."""
    name = product_name.upper()

    # Explicit grams/kg/ml in name
    m = re.search(r"\b(\d[\d,.]*)\s*(KG|GR?|ML|CL)\b", name, re.I)
    if m:
        qty, unit = m.group(1).replace(",", "."), m.group(2).upper()
        grams = float(qty) * (1000 if unit == "KG" else 10 if unit == "CL" else 1)
        return f"{int(grams)}g from label"

    # Piece count × unit weight
    m = _PIECE_RE.search(name)
    if m:
        n = int(next(g for g in m.groups() if g is not None))
        for food, wt in _UNIT_WEIGHTS.items():
            if food in name:
                return f"{n} pieces × ~{wt}g = ~{n * wt}g"
        return f"{n} pieces (unit weight unknown)"

    # Multiplier packs: 6X33CL, 4X125G
    m = re.search(r"\b(\d+)\s*[Xx]\s*(\d+)\s*(G|ML|CL|KG)\b", name, re.I)
    if m:
        n, qty, unit = int(m.group(1)), float(m.group(2)), m.group(3).upper()
        grams = qty * n * (1000 if unit == "KG" else 10 if unit == "CL" else 1)
        return f"{n}×{int(qty)}{unit} = ~{int(grams)}g"

    return None


def infer_grams(product_name: str) -> float | None:
    """Try to extract grams numerically from the product name."""
    name = product_name.upper()

    # Explicit weight in label
    m = re.search(r"\b(\d[\d,.]*)\s*(KG|GR?)\b", name, re.I)
    if m:
        qty, unit = m.group(1).replace(",", "."), m.group(2).upper()
        return float(qty) * (1000 if unit == "KG" else 1)

    m = re.search(r"\b(\d[\d,.]*)\s*(ML|CL)\b", name, re.I)
    if m:
        qty, unit = m.group(1).replace(",", "."), m.group(2).upper()
        return float(qty) * (10 if unit == "CL" else 1)

    # Piece count × known unit weight
    pm = _PIECE_RE.search(name)
    if pm:
        n = int(next(g for g in pm.groups() if g is not None))
        for food, wt in _UNIT_WEIGHTS.items():
            if food in name:
                return float(n * wt)

    return None


def generate_requests(
    purchases_csv: Path,
    out_path: Path,
    min_count: int = 2,
) -> int:
    """Write unmatched items (count >= min_count) to a JSONL request file.

    Each line includes the product name, occurrence count, median price, and
    a weight_hint so the agent can infer grams accurately.
    """
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
            hint = _extract_weight_hint(row["product_name"])
            entry: dict = {
                "product_name": row["product_name"],
                "count": int(row["count"]),
                "median_price_eur": None if pd.isna(row["median_price"]) else round(float(row["median_price"]), 2),
            }
            if hint:
                entry["weight_hint"] = hint
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"Wrote {len(grp)} requests to {out_path}")
    return len(grp)


def enrich_purchases(mapping_csv: Path, purchases_csv: Path) -> int:
    """Re-enrich purchases from mapping and sanitize stale pyfooda keys.

    Safe to run any time: reads mapping, re-applies to purchases, downgrades
    any match rows whose pyfooda key no longer exists in the current DB.
    """
    foods = set(get_pyfooda_foods_df()["display_name"].dropna().astype(str))
    mapping = pd.read_csv(mapping_csv, dtype=str)
    mapping["delhaize_name"] = mapping["delhaize_name"].fillna("").str.upper()
    mapping["action"] = mapping["action"].fillna("")
    mapping["pyfooda_name"] = mapping["pyfooda_name"].fillna("")

    # Sanitize stale keys in mapping
    stale = (mapping["action"].str.lower() == "match") & (~mapping["pyfooda_name"].isin(foods))
    if stale.any():
        mapping.loc[stale, "action"] = "ignore"
        mapping.loc[stale, "pyfooda_name"] = ""
        mapping.loc[stale, "grams"] = ""
        mapping.to_csv(mapping_csv, index=False)

    purchases = pd.read_csv(purchases_csv, dtype=str)
    purchases["product_name"] = purchases["product_name"].fillna("").str.upper()

    # Apply grams inference for items with null grams where label gives us information
    lookup = mapping.set_index("delhaize_name")[["action", "pyfooda_name", "grams"]].to_dict("index")
    purchases["llm_action"] = purchases["product_name"].map(lambda n: lookup.get(n, {}).get("action", "ignore"))
    purchases["pyfooda_name"] = purchases["product_name"].map(lambda n: lookup.get(n, {}).get("pyfooda_name", ""))

    def _grams(row: pd.Series) -> str:
        mapped_grams = lookup.get(row["product_name"], {}).get("grams", "")
        if mapped_grams and str(mapped_grams).strip():
            return str(mapped_grams)
        inferred = infer_grams(row["product_name"])
        return str(inferred) if inferred is not None else ""

    purchases["grams_in_name"] = purchases.apply(_grams, axis=1)

    # Final guard
    bad = (purchases["llm_action"].fillna("").str.lower() == "match") & (
        ~purchases["pyfooda_name"].fillna("").isin(foods)
    )
    purchases.loc[bad, "llm_action"] = "ignore"
    purchases.loc[bad, "pyfooda_name"] = ""
    purchases.loc[bad, "grams_in_name"] = ""
    purchases.to_csv(purchases_csv, index=False)

    matched = int((purchases["llm_action"].fillna("").str.lower() == "match").sum())
    stale_count = int(stale.sum())
    if stale_count:
        print(f"  Sanitized {stale_count} stale mapping keys")
    print(f"  {matched} matched purchase rows after enrich")
    return matched


def apply_responses(
    mapping_csv: Path,
    purchases_csv: Path,
    responses_path: Path,
) -> tuple[int, int]:
    """Read agent responses, apply to mapping, then re-enrich purchases."""
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
        if not name:
            continue
        action = str(resp.get("action", "match")).lower()
        pyfooda_name = str(resp.get("pyfooda_name", "")).strip()
        grams = resp.get("grams")

        if action == "ignore":
            row_data = {"action": "ignore", "pyfooda_name": "", "llm_raw_name": "", "grams": ""}
            ignored += 1
        elif pyfooda_name and pyfooda_name in foods:
            row_data = {
                "action": "match",
                "pyfooda_name": pyfooda_name,
                "llm_raw_name": pyfooda_name,
                "grams": "" if grams is None else str(grams),
            }
            applied += 1
        else:
            continue  # invalid key — skip silently

        mask = mapping["delhaize_name"] == name
        if mask.any():
            for col, val in row_data.items():
                mapping.loc[mask, col] = val
        else:
            mapping.loc[len(mapping)] = {"delhaize_name": name, **row_data}

    mapping = mapping.drop_duplicates(subset=["delhaize_name"], keep="last").reset_index(drop=True)
    mapping.to_csv(mapping_csv, index=False)
    print(f"Applied {applied} matches, {ignored} ignores")

    matched = enrich_purchases(mapping_csv, purchases_csv)
    return applied, matched


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent-driven remap — single matching entry point")
    parser.add_argument("--generate", action="store_true", help="Write unmatched items to requests JSONL")
    parser.add_argument("--apply", action="store_true", help="Apply agent responses JSONL to mapping + purchases")
    parser.add_argument("--enrich", action="store_true", help="Re-enrich purchases from existing mapping (no responses needed)")
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
    elif args.enrich:
        enrich_purchases(args.mapping, args.purchases)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
