"""Local unmatched-item remapper (no external LLM provider required).

Workflow:
- read purchases_enriched.csv and find highest-count unmatched product names;
- propose pyfooda matches with deterministic lexical scoring;
- optionally apply high-confidence matches to mapping + purchases files.
"""

from __future__ import annotations

import argparse
import difflib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .common import DEFAULT_MAPPING, DEFAULT_PURCHASES, get_pyfooda_foods_df, normalize_food_query


_EXTRA_ALIASES = {
    "mozza": "mozzarella",
    "mozza": "mozzarella",
    "mozz": "mozzarella",
    "epinard": "spinach",
    "epinards": "spinach",
    "courgette": "zucchini",
    "courgettes": "zucchini",
    "boeuf": "beef",
    "agneau": "lamb",
    "veau": "veal",
    "porc": "pork",
    "poulet": "chicken",
    "pomme": "apple",
    "patate": "potato",
    "pain": "bread",
    "fraise": "strawberry",
    "myrtille": "blueberry",
    "myrtilles": "blueberries",
    "ciboulette": "chives",
}

_STOP_TOKENS = {
    "bio",
    "emb",
    "mini",
    "maxi",
    "light",
    "naturel",
    "natural",
    "classic",
    "pack",
    "pcs",
    "pc",
    "gr",
    "g",
    "kg",
    "ml",
    "cl",
    "l",
}


@dataclass
class MatchProposal:
    product_name: str
    count: int
    candidate: str | None
    confidence: str
    score: float
    gap: float
    query: str


class LocalRemapSkill:
    """Deterministic remapper based on lexical overlap and string similarity."""

    def __init__(self) -> None:
        foods = get_pyfooda_foods_df()["display_name"].dropna().drop_duplicates().astype(str)
        self.food_names: list[str] = foods.tolist()
        self.food_norms: list[str] = [self._norm_food_name(name) for name in self.food_names]
        self.valid_foods: set[str] = set(self.food_names)
        self.token_index: dict[str, set[int]] = {}
        for idx, norm_name in enumerate(self.food_norms):
            for tok in set(self._tokens(norm_name)):
                self.token_index.setdefault(tok, set()).add(idx)

    @staticmethod
    def _strip_accents(text: str) -> str:
        normed = unicodedata.normalize("NFKD", text)
        return "".join(ch for ch in normed if not unicodedata.combining(ch))

    def _norm_food_name(self, text: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", self._strip_accents(text).lower()).strip()

    def _normalize_query(self, product_name: str) -> str:
        query = normalize_food_query(product_name)
        for src, dst in _EXTRA_ALIASES.items():
            query = re.sub(rf"\b{re.escape(src)}\b", dst, query)
        query = re.sub(r"\b\d+[a-z]*\b", " ", query)
        query = re.sub(r"\s+", " ", query).strip()
        return query

    def _tokens(self, text: str) -> list[str]:
        toks = [tok for tok in text.split() if len(tok) >= 3 and tok not in _STOP_TOKENS]
        return toks

    def _candidate_ids(self, q_tokens: list[str]) -> set[int]:
        postings = [self.token_index.get(tok, set()) for tok in q_tokens if tok in self.token_index]
        postings = [p for p in postings if p]
        if not postings:
            return set()
        postings.sort(key=len)
        ids = set(postings[0])
        for post in postings[1:3]:
            ids &= post
            if ids:
                break
        if ids:
            return ids
        ids = set()
        for post in postings[:3]:
            ids |= post
        return ids

    def propose(self, product_name: str, count: int) -> MatchProposal:
        query = self._normalize_query(product_name)
        if not query:
            return MatchProposal(product_name, count, None, "none", 0.0, 0.0, query)

        q_tokens = self._tokens(query)
        if not q_tokens:
            return MatchProposal(product_name, count, None, "none", 0.0, 0.0, query)

        # Fast path: exact normalized match.
        for idx, norm_name in enumerate(self.food_norms):
            if norm_name == query:
                return MatchProposal(product_name, count, self.food_names[idx], "high", 99.0, 99.0, query)

        cand_ids = self._candidate_ids(q_tokens)
        if not cand_ids:
            return MatchProposal(product_name, count, None, "none", 0.0, 0.0, query)

        scored: list[tuple[float, int]] = []
        q_set = set(q_tokens)
        for idx in cand_ids:
            name_norm = self.food_norms[idx]
            n_tokens = set(self._tokens(name_norm))
            overlap = len(q_set & n_tokens)
            if overlap == 0:
                continue
            coverage = overlap / max(len(q_set), 1)
            ratio = difflib.SequenceMatcher(None, query, name_norm).ratio()
            score = overlap + (coverage * 3.0) + ratio
            scored.append((score, idx))

        if not scored:
            return MatchProposal(product_name, count, None, "none", 0.0, 0.0, query)

        scored.sort(key=lambda x: (-x[0], len(self.food_names[x[1]]), self.food_names[x[1]]))
        best_score, best_idx = scored[0]
        second_score = scored[1][0] if len(scored) > 1 else 0.0
        gap = best_score - second_score

        best_norm = self.food_norms[best_idx]
        overlap = len(set(q_tokens) & set(self._tokens(best_norm)))
        coverage = overlap / max(len(set(q_tokens)), 1)
        ratio = difflib.SequenceMatcher(None, query, best_norm).ratio()

        if coverage >= 1.0 and ratio >= 0.72 and gap >= 0.25:
            confidence = "high"
        elif coverage >= 0.67 and ratio >= 0.65 and gap >= 0.20:
            confidence = "medium"
        else:
            confidence = "low"

        return MatchProposal(
            product_name=product_name,
            count=count,
            candidate=self.food_names[best_idx],
            confidence=confidence,
            score=round(best_score, 4),
            gap=round(gap, 4),
            query=query,
        )


def load_unmatched_counts(purchases_csv: Path, min_count: int, top_n: int) -> pd.DataFrame:
    data = pd.read_csv(purchases_csv, dtype=str)
    action = data["llm_action"].fillna("").str.lower()
    unmatched = data[action != "match"].copy()
    counts = (
        unmatched.groupby("product_name").size().reset_index(name="count").sort_values("count", ascending=False)
    )
    counts = counts[counts["count"] >= min_count]
    if top_n > 0:
        counts = counts.head(top_n)
    return counts.reset_index(drop=True)


def apply_proposals(mapping_csv: Path, purchases_csv: Path, proposals_df: pd.DataFrame, min_confidence: str) -> tuple[int, int]:
    rank = {"high": 3, "medium": 2, "low": 1, "none": 0}
    cutoff = rank[min_confidence]

    selected = proposals_df[
        (proposals_df["candidate"].notna())
        & (proposals_df["confidence"].map(rank).fillna(0) >= cutoff)
    ].copy()

    if selected.empty:
        return 0, 0

    mapping = pd.read_csv(mapping_csv, dtype=str)
    mapping["delhaize_name"] = mapping["delhaize_name"].astype(str).str.upper()

    applied = 0
    for _, row in selected.iterrows():
        name = str(row["product_name"]).upper()
        candidate = str(row["candidate"])
        mask = mapping["delhaize_name"] == name
        if mask.any():
            mapping.loc[mask, "action"] = "match"
            mapping.loc[mask, "pyfooda_name"] = candidate
            mapping.loc[mask, "llm_raw_name"] = candidate
            applied += 1
        else:
            mapping.loc[len(mapping)] = {
                "delhaize_name": name,
                "action": "match",
                "pyfooda_name": candidate,
                "llm_raw_name": candidate,
                "grams": "",
            }
            applied += 1

    mapping = mapping.drop_duplicates(subset=["delhaize_name"], keep="last").reset_index(drop=True)
    mapping.to_csv(mapping_csv, index=False)

    purchases = pd.read_csv(purchases_csv, dtype=str)
    purchases["product_name"] = purchases["product_name"].astype(str).str.upper()
    lookup = mapping.set_index("delhaize_name")[["action", "pyfooda_name", "grams"]].to_dict("index")

    purchases["llm_action"] = purchases["product_name"].map(lambda n: lookup.get(n, {}).get("action", "ignore"))
    purchases["pyfooda_name"] = purchases["product_name"].map(lambda n: lookup.get(n, {}).get("pyfooda_name", ""))
    purchases["grams_in_name"] = purchases["product_name"].map(lambda n: lookup.get(n, {}).get("grams", ""))
    purchases.to_csv(purchases_csv, index=False)

    matched_rows = int((purchases["llm_action"].fillna("").str.lower() == "match").sum())
    return applied, matched_rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Local deterministic remap for highest-count unmatched products")
    parser.add_argument("--purchases", type=Path, default=DEFAULT_PURCHASES)
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument("--top", type=int, default=200, help="How many unmatched product names to inspect")
    parser.add_argument("--min-count", type=int, default=2, help="Minimum occurrence count for unmatched names")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply selected mappings directly to mapping + purchases files",
    )
    parser.add_argument(
        "--min-confidence",
        choices=["high", "medium", "low"],
        default="high",
        help="Minimum confidence level to apply when --apply is set",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/local_remap_proposals.csv"),
        help="CSV file to write proposals",
    )
    args = parser.parse_args()

    counts = load_unmatched_counts(args.purchases, min_count=args.min_count, top_n=args.top)
    skill = LocalRemapSkill()

    proposals = [skill.propose(str(row["product_name"]), int(row["count"])) for _, row in counts.iterrows()]
    out_df = pd.DataFrame(
        {
            "product_name": [p.product_name for p in proposals],
            "count": [p.count for p in proposals],
            "candidate": [p.candidate for p in proposals],
            "confidence": [p.confidence for p in proposals],
            "score": [p.score for p in proposals],
            "gap": [p.gap for p in proposals],
            "query": [p.query for p in proposals],
        }
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(args.output, index=False)

    print(f"Wrote proposals: {args.output} ({len(out_df)} rows)")
    print("Confidence breakdown:")
    print(out_df["confidence"].value_counts().to_string())

    if args.apply:
        applied, matched_rows = apply_proposals(args.mapping, args.purchases, out_df, args.min_confidence)
        print(f"Applied mappings: {applied}")
        print(f"Matched purchase rows now: {matched_rows}")


if __name__ == "__main__":
    main()
