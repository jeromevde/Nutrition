"""Normalize grocery source exports into the canonical purchase schema.

Canonical columns:
product_name, price, barcode, date, source_file, source
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd

CANONICAL_COLUMNS = ["product_name", "price", "barcode", "date", "source_file", "source"]
GENERATED_DATA_FILES = {
    "delhaize_mapping.csv",
    "nutrition_pertrip.csv",
    "nutrition_yearly.csv",
    "purchases_enriched.csv",
    "purchases_normalized.csv",
}
_NON_FOOD_RE = re.compile(
    r"""
    # Payment / receipt noise lines
    ^\s*(TOTAL|TOTAAL|SOUS.?TOTAL|TVA|BTW|REMISE|REDUCTION|PROMOTIE|KORTINGS?|RETOUR
      |VISA|BANCONTACT|MASTERCARD|ESPECES|MONNAIE|WISSELGELD
      |\d+\s*[xX]\s*$
      |0,\d+\s*[Kk][Gg]\s*[xX]
      |\d{6,}
    )\s*$
    # Household / hygiene / non-food products
    |\b(SERVIETTES?|NAPKINS?|FLEURS?|FLOWERS?|BOUGIES?|CANDLES?|ALCOOL|ALCOHOL
      |TRAITEUR|LIEN|FIX
      |DENTIFRICE|DENTIF|SHAMPO+|DEODORAN?T|SAVON|SOAP|DETERGENT|LESSIVE
      |ORAL.?B|COLGATE|SENSODYNE|GILLETTE|PAMPERS|COUCHE[S]?
      |FEBREZE|ARIEL|DASH|PERSIL|BOLD|LENOR|DREFT
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Receipt lines that are not purchases: totals, payment, loyalty points, VAT,
# discounts. Before this filter, a 6 096-point loyalty balance was counted as a
# EUR 6 096 product. Kept separate from _NON_FOOD_RE because these are matched
# anywhere in the line, not only as a whole line.
_RECEIPT_META_RE = re.compile(
    r"^TOTAA?L|SOUS[- ]?TOTAL|SUBTOTAA?L|^TOT\b"
    r"|SOLDE DE POINTS|\bPOINTS\b|PUNTEN"
    r"|\bCHEQ|BANCONTACT|MAESTRO|\bVISA\b|MASTERCARD|BETAALD|ESPECES|CONTANT|\bCASH\b|PAIEMENT|BETALING"
    r"|\bBTW\b|\bTVA\b|\bHTVA\b"
    r"|KORTING|REMISE|RISTOURNE|REDUCTION|NUTRI-BOOST|GRATUIT|1/2 PRIX"
    r"|^SN\s*\d|^GS\s*:|^EUR\b|CARTE (CREDIT|CLIENT)|KLANTEN|\bXTRA\b"
    r"|NOMBRE D ARTICLES|AANTAL ARTIKELEN|^A PAYER|TE BETALEN"
    r"|^\d+[.,]?\d*\s*KG\s*X$|^\d{1,6}$",
    re.IGNORECASE,
)
# A single grocery line above this price on a Belgian supermarket receipt is a
# total or a payment instrument that OCR mislabelled, not a product.
MAX_LINE_PRICE_EUR = 100.0


class SourceNormalizerSkill:
    """Convert OCR/scraper CSVs from any retailer into one canonical shape."""

    def normalize_csv(self, path: Path | str, *, source: str | None = None, date: str | None = None) -> pd.DataFrame:
        path = Path(path)
        if path.name in GENERATED_DATA_FILES:
            raise ValueError(f"Skipping generated data file: {path.name}")
        data = pd.read_csv(path, dtype=str)
        normalized = pd.DataFrame()
        normalized["product_name"] = self._product_column(data).astype(str).str.strip().str.upper()
        normalized["price"] = pd.to_numeric(self._optional_column(data, "price"), errors="coerce")
        normalized["barcode"] = self._optional_column(data, "barcode").fillna("").astype(str)
        normalized["date"] = date or self._date_from_path(path)
        normalized["source_file"] = path.name
        normalized["source"] = source or path.parent.name
        return self.filter_food_rows(normalized)

    def normalize_many(self, paths: list[Path], *, source: str | None = None) -> pd.DataFrame:
        frames = []
        for path in paths:
            if path.is_dir():
                for csv_path in sorted(path.glob("*.csv")):
                    try:
                        frames.append(self.normalize_csv(csv_path, source=source))
                    except Exception:
                        continue
            else:
                try:
                    frames.append(self.normalize_csv(path, source=source))
                except Exception:
                    continue
        if not frames:
            return pd.DataFrame(columns=CANONICAL_COLUMNS)
        return pd.concat(frames, ignore_index=True)[CANONICAL_COLUMNS]

    @staticmethod
    def filter_food_rows(data: pd.DataFrame) -> pd.DataFrame:
        data = data.dropna(subset=["product_name"]).copy()
        data = data[data["product_name"].astype(str).str.len() > 0]
        names = data["product_name"].astype(str)
        data = data[~names.apply(lambda name: bool(_NON_FOOD_RE.match(name)))]
        data = data[~data["product_name"].astype(str).apply(lambda name: bool(_RECEIPT_META_RE.search(name)))]
        if "price" in data.columns:
            price = data["price"].fillna(0)
            data = data[(price >= 0) & (price < MAX_LINE_PRICE_EUR)]
        return data.reset_index(drop=True)

    @staticmethod
    def _product_column(data: pd.DataFrame) -> pd.Series:
        for candidate in ("product_name", "name", "description", "item", "label"):
            if candidate in data.columns:
                return data[candidate]
        raise ValueError("input CSV must contain a product_name/name/description/item/label column")

    @staticmethod
    def _optional_column(data: pd.DataFrame, name: str) -> pd.Series:
        if name in data.columns:
            return data[name]
        return pd.Series([None] * len(data))

    @staticmethod
    def _date_from_path(path: Path) -> str | None:
        match = re.search(r"(\d{4})[_-](\d{2})[_-](\d{2})", path.stem)
        if not match:
            return None
        year, month, day = match.groups()
        if int(month) > 12:
            month, day = day, month
        return f"{year}-{month}-{day}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize grocery CSVs into the canonical purchase schema")
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--source", default=None)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    data = SourceNormalizerSkill().normalize_many(args.inputs, source=args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(args.output, index=False)
    print(f"Wrote {len(data):,} rows to {args.output}")


if __name__ == "__main__":
    main()
