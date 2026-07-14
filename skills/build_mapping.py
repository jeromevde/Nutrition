"""Build and maintain Delhaize -> pyfooda mapping using reusable skills.

This pipeline intentionally avoids hardcoded product-category keyword rules.
It delegates matching to ``skills.matcher.MatcherSkill`` and can optionally
run an agentic repair pass from ``skills.report_verifier`` findings.
"""

from __future__ import annotations

import argparse
import glob
import re
from pathlib import Path

import pandas as pd

from .common import DELHAIZE_SCRAPER_DIR, DEFAULT_MAPPING, DEFAULT_PURCHASES
from .matcher import MatcherSkill
from .report_verifier import ReportVerifierSkill

_NON_FOOD_RE = re.compile(
    r"""
    ^\s*(
        NUTRI.?BOOST
      | \d+EME\s+[AÀ]
      | \d+E\s+[AÀ]
      | \d+\+\d+\s+GRATUIT
      | TOTAL
      | SOUS.TOTAL
      | TVA
      | REMISE
      | REDUCTION
      | PROMOTIE
      | KORTINGS?
      | RETOUR
      | ESPECES
      | VISA
      | MASTERCARD
      | BANCONTACT
      | MONNAIE
      | [0-9]+\s*[xX]\s*$
      | 0,\d+\s+[Kk][Gg]\s+[xX]
      | \d{6,}
    )\s*$
    """,
    re.VERBOSE | re.IGNORECASE,
)


def _load_ticket_rows(ticket_dir: Path) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in sorted(glob.glob(str(ticket_dir / "*.csv"))):
        stem = Path(path).stem
        m = re.match(r"(\d{4})_(\d{2})_(\d{2})", stem)
        if not m:
            continue
        year, month, day = m.groups()
        if int(month) > 12:
            month, day = day, month
        date_str = f"{year}-{month}-{day}"
        try:
            df = pd.read_csv(path, dtype=str)
        except Exception:
            continue
        if "product_name" not in df.columns:
            continue
        df["date"] = date_str
        df["source_file"] = Path(path).name
        frames.append(df)

    if not frames:
        raise RuntimeError(f"No ticket CSVs found in {ticket_dir}")

    all_rows = pd.concat(frames, ignore_index=True)
    all_rows["product_name"] = all_rows["product_name"].astype(str).str.strip().str.upper()
    all_rows["date"] = pd.to_datetime(all_rows["date"], errors="coerce")
    all_rows["price"] = pd.to_numeric(all_rows.get("price"), errors="coerce")
    all_rows = all_rows.dropna(subset=["product_name", "date"])
    return all_rows


def _filter_purchases(df: pd.DataFrame) -> pd.DataFrame:
    filtered = df[df["price"].fillna(0) >= 0].copy()
    mask = filtered["product_name"].apply(lambda n: bool(_NON_FOOD_RE.match(str(n))))
    return filtered[~mask].copy()


def _extract_verifier_product_names() -> set[str]:
    skill = ReportVerifierSkill()
    result = skill.verify()
    names: set[str] = set()
    for finding in result.get("findings", []):
        if finding.get("kind") != "suspect_mapping":
            continue
        examples = finding.get("evidence", {}).get("examples", {})
        for product_name in examples.keys():
            if product_name:
                names.add(str(product_name).strip().upper())
    return names


def _merge_mapping(existing: pd.DataFrame, fresh: pd.DataFrame) -> pd.DataFrame:
    merged = pd.concat([existing, fresh], ignore_index=True)
    merged = merged.drop_duplicates(subset=["delhaize_name"], keep="last")
    return merged.reset_index(drop=True)


def _enrich_purchases(purchases: pd.DataFrame, mapping_df: pd.DataFrame) -> pd.DataFrame:
    lookup = mapping_df.set_index("delhaize_name")[["pyfooda_name", "grams", "action"]].to_dict("index")

    def enrich_row(row: pd.Series) -> pd.Series:
        info = lookup.get(str(row["product_name"]).upper(), {})
        return pd.Series(
            {
                "pyfooda_name": info.get("pyfooda_name", ""),
                "grams_in_name": info.get("grams"),
                "llm_action": info.get("action", "unknown"),
            }
        )

    return purchases.join(purchases.apply(enrich_row, axis=1))


def run_pipeline(
    *,
    ticket_dir: Path,
    mapping_csv: Path,
    purchases_csv: Path,
    model: str,
    batch_size: int,
    top_n: int,
    force: bool,
    remap_names: set[str] | None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = _load_ticket_rows(ticket_dir)
    purchases = _filter_purchases(raw)

    if mapping_csv.exists() and not force:
        existing = pd.read_csv(mapping_csv)
    else:
        existing = pd.DataFrame(columns=["delhaize_name", "action", "pyfooda_name", "llm_raw_name", "grams"])

    all_names = set(purchases["product_name"].dropna().astype(str).str.upper().unique())
    already = set(existing["delhaize_name"].astype(str).str.upper()) if not existing.empty else set()

    if remap_names:
        target_names = sorted(n for n in all_names if n in remap_names)
        if target_names:
            existing = existing[~existing["delhaize_name"].astype(str).str.upper().isin(remap_names)].reset_index(drop=True)
    else:
        target_names = sorted(n for n in all_names if n not in already)

    price_map = (
        purchases.groupby("product_name")["price"]
        .median()
        .dropna()
        .to_dict()
    )

    matcher = MatcherSkill(batch_size=batch_size, top_n=top_n, model=model, dry_run=False)
    results = matcher.match_names(target_names, price_map)

    fresh = pd.DataFrame(
        {
            "delhaize_name": [r.delhaize_name for r in results],
            "action": [r.action for r in results],
            "pyfooda_name": [r.pyfooda_name for r in results],
            "llm_raw_name": [r.llm_raw_name for r in results],
            "grams": [r.grams for r in results],
        }
    )

    mapping_df = _merge_mapping(existing, fresh)
    mapping_df.to_csv(mapping_csv, index=False)

    enriched = _enrich_purchases(purchases, mapping_df)
    enriched.to_csv(purchases_csv, index=False)
    return mapping_df, enriched


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Delhaize mapping using matcher skill")
    parser.add_argument("--ticket-dir", type=Path, default=DELHAIZE_SCRAPER_DIR)
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument("--purchases", type=Path, default=DEFAULT_PURCHASES)
    parser.add_argument("--model", type=str, default="google/gemini-2.0-flash-001")
    parser.add_argument("--batch-size", type=int, default=40)
    parser.add_argument("--top-n", type=int, default=12)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--remap-from-verifier", action="store_true")
    args = parser.parse_args()

    remap_names = _extract_verifier_product_names() if args.remap_from_verifier else None
    mapping_df, enriched = run_pipeline(
        ticket_dir=args.ticket_dir,
        mapping_csv=args.mapping,
        purchases_csv=args.purchases,
        model=args.model,
        batch_size=args.batch_size,
        top_n=args.top_n,
        force=args.force,
        remap_names=remap_names,
    )

    matched = int((enriched["llm_action"] == "match").sum())
    print(f"Saved mapping: {args.mapping} ({len(mapping_df)} rows)")
    print(f"Saved purchases: {args.purchases} ({len(enriched)} rows)")
    print(f"Matched purchase rows: {matched}/{len(enriched)} ({matched / max(len(enriched), 1) * 100:.1f}%)")


if __name__ == "__main__":
    main()
