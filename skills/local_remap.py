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

from .common import (
    DEFAULT_MAPPING,
    DEFAULT_PURCHASES,
    build_food_search_index,
    get_pyfooda_foods_df,
    normalize_food_query,
)


_EXTRA_ALIASES = {
    # FR/NL -> EN protein/dairy/fish
    "mozza": "mozzarella",
    "mozz": "mozzarella",
    "boeuf": "beef",
    "agneau": "lamb",
    "veau": "veal",
    "porc": "pork",
    "poulet": "chicken",
    "saumon": "salmon",
    "maquereau": "mackerel",
    "hareng": "herring",
    "jambon": "ham",
    "saucisse": "sausage",
    "lardons": "bacon",
    "escalope": "veal",
    "roti": "roast",
    # FR/NL -> EN produce
    "epinard": "spinach",
    "epinards": "spinach",
    "courgette": "zucchini",
    "courgettes": "zucchini",
    "aubergine": "eggplant",
    "aubergines": "eggplant",
    "oignon": "onion",
    "oignons": "onion",
    "fenouil": "fennel",
    "fenouils": "fennel",
    "poire": "pear",
    "poires": "pear",
    "pomme": "apple",
    "pasteque": "watermelon",
    "cerise": "cherry",
    "cerises": "cherry",
    "tomate": "tomato",
    "tomates": "tomato",
    "pois": "peas",
    "patate": "potato",
    "grenaille": "potato",
    "chou": "cabbage",
    "choux": "cabbage",
    "roquette": "arugula",
    "mesclun": "mixed greens",
    "haricot": "green beans",
    "haricots": "green beans",
    "pousses": "sprouts",
    # FR/NL -> EN bread/grain
    "pain": "bread",
    "stokbrood": "baguette",
    "toast": "bread",
    "wrap": "wraps",
    "wraps": "wraps",
    "gaufre": "waffle",
    "galette": "cracker",
    "biscuit": "cookie",
    # FR/NL -> EN dairy/deli
    "beurre": "butter",
    "fromage": "cheese",
    "creme": "cream",
    "ciboulette": "chives",
    "activia": "yogurt",
    "yaourt": "yogurt",
    "yoghourt": "yogurt",
    "houmous": "hommus",
    "hummous": "hummus",
    # FR/NL -> EN sweet/snack
    "chocolat": "chocolate",
    "nutella": "hazelnut spread",
    "fraise": "strawberry",
    "fraises": "strawberry",
    "myrtille": "blueberry",
    "myrtilles": "blueberries",
    # FR/NL -> EN drinks
    "cafe": "coffee",
    "jus": "juice",
}

_PHRASE_ALIASES = {
    "de cecco": "pasta",
    "pain de mie": "bread",
    "stokbrood": "baguette",
    "petit pain": "bread",
    "haricots verts": "green beans",
    "haricot vert": "green beans",
    "jeune pousse": "mixed greens",
    "jeunes pousses": "mixed greens",
    "pdt grenaille": "potato",
    "pomme de terre": "potato",
    "pate a pizza": "pizza dough",
    "roti de veau": "veal",
    "escalope de veau": "veal",
    "escalope veau": "veal",
    "cream cheese": "cream cheese",
    "fromage frais": "cream cheese",
}

# High-precision multilingual concept anchors.
# If a pattern is present, force a known-valid canonical key.
# Ordered: most specific first.
_CONCEPT_TARGETS: list[tuple[re.Pattern[str], str]] = [
    # Compound / multi-word first
    (re.compile(r"\b(cerise|cherry)\b.*\b(tomato|tomate|tom)\b|\b(tomato|tomate|tom)\b.*\b(cerise|cherry)\b", re.I), "CHERRY TOMATOES"),
    (re.compile(r"\b(haricot|haricots)\s*(vert|verts|green)\b", re.I), "GREEN BEANS"),
    (re.compile(r"\b(jeune|jeunes)\s*pousse[s]?\b", re.I), "MIXED GREENS"),
    (re.compile(r"\b(pate|pâte)\s*(a|à)\s*pizza\b", re.I), "PIZZA DOUGH"),
    (re.compile(r"\b(cream\s*cheese|fromage\s*frais)\b", re.I), "CREAM CHEESE"),
    # Single-concept
    (re.compile(r"\b(banane|bananes|banana|bananas)\b", re.I), "BANANA"),
    (re.compile(r"\b(oeuf|oeufs|egg|eggs)\b", re.I), "EGGS"),
    (re.compile(r"\bduchesse\b", re.I), "POTATOES"),
    (re.compile(r"\bgrenaille\b", re.I), "POTATOES"),
    (re.compile(r"\b(lindt|excellence)\b", re.I), "LINDT, EXCELLENCE DARK CHOCOLATE"),
    (re.compile(r"\b(epinard|epinards|spinach)\b", re.I), "SPINACH"),
    (re.compile(r"\b(mozza|mozzarella)\b", re.I), "MOZZARELLA"),
    (re.compile(r"\b(houmous|hummus|hommus)\b", re.I), "HOMMUS"),
    (re.compile(r"\b(activia|yogurt|yoghurt|yaourt)\b", re.I), "YOGURT"),
    (re.compile(r"\bwraps?\b", re.I), "WRAPS"),
    (re.compile(r"\btoast\b", re.I), "BREAD"),
    (re.compile(r"\b(fraise|fraises|strawberr(y|ies))\b", re.I), "STRAWBERRIES"),
    (re.compile(r"\b(myrtille|myrtilles|blueberr(y|ies))\b", re.I), "BLUEBERRIES"),
    (re.compile(r"\b(saumon|salmon)\b", re.I), "SALMON"),
    (re.compile(r"\b(beurre|butter)\b", re.I), "BUTTER"),
    (re.compile(r"\b(oignon|oignons|onion|onions)\b", re.I), "ONION"),
    (re.compile(r"\b(aubergine|aubergines|eggplant)\b", re.I), "EGGPLANT"),
    (re.compile(r"\b(fenouil|fenouils|fennel)\b", re.I), "Fennel, bulb, raw"),
    (re.compile(r"\b(pasteque|pastèque|watermelon)\b", re.I), "WATERMELON"),
    (re.compile(r"\b(poire|poires|pear|pears)\b", re.I), "PEAR"),
    (re.compile(r"\b(roquette|arugula|rocket)\b", re.I), "ARUGULA"),
    (re.compile(r"\b(mesclun)\b", re.I), "MIXED GREENS"),
    (re.compile(r"\b(maquereau|mackerel)\b", re.I), "MACKEREL"),
    (re.compile(r"\b(hareng|herring)\b", re.I), "Fish, herring"),
    (re.compile(r"\b(gnocchi|gnocch)\b", re.I), "GNOCCHI"),
    (re.compile(r"\b(mayonnaise|mayo)\b", re.I), "MAYONNAISE"),
    (re.compile(r"\b(salami|rosette)\b", re.I), "SALAMI"),
    (re.compile(r"\b(gaufre|gaufres|waffle|waffles)\b", re.I), "WAFFLE"),
    (re.compile(r"\b(philadelphia|philly)\b", re.I), "CREAM CHEESE"),
    (re.compile(r"\b(dinosaurus|dinosaur|dino)\b.*\b(choc|chocolat|chocolate)\b|\b(choc|chocolat|chocolate)\b.*\b(dinosaurus|dinosaur|dino)\b", re.I), "CHOCOLATE"),
    (re.compile(r"\b(nutella)\b", re.I), "FERRERO, NUTELLA, HAZELNUT SPREAD WITH COCOA"),
    (re.compile(r"\b(lavazza|nespresso|espresso|cafe|coffee)\b", re.I), "COFFEE"),
]

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

    def __init__(self, *, use_semantic: bool = True, semantic_top_n: int = 40) -> None:
        foods = get_pyfooda_foods_df()["display_name"].dropna().drop_duplicates().astype(str)
        self.food_names: list[str] = foods.tolist()
        self.food_norms: list[str] = [self._norm_food_name(name) for name in self.food_names]
        self.valid_foods: set[str] = set(self.food_names)
        self.semantic_top_n = max(int(semantic_top_n), 0)
        self.search_index = None
        self.name_to_ids: dict[str, list[int]] = {}
        self.norm_to_ids: dict[str, list[int]] = {}
        self.token_index: dict[str, set[int]] = {}
        for idx, norm_name in enumerate(self.food_norms):
            self.name_to_ids.setdefault(self.food_names[idx], []).append(idx)
            self.norm_to_ids.setdefault(norm_name, []).append(idx)
            for tok in set(self._tokens(norm_name)):
                self.token_index.setdefault(tok, set()).add(idx)
        self.vocab_tokens = sorted(self.token_index.keys())
        if use_semantic and self.semantic_top_n > 0:
            try:
                self.search_index = build_food_search_index()
            except ModuleNotFoundError:
                self.search_index = None

    @staticmethod
    def _strip_accents(text: str) -> str:
        normed = unicodedata.normalize("NFKD", text)
        return "".join(ch for ch in normed if not unicodedata.combining(ch))

    def _norm_food_name(self, text: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", self._strip_accents(text).lower()).strip()

    def _normalize_query(self, product_name: str) -> str:
        query = normalize_food_query(product_name)
        for src, dst in _PHRASE_ALIASES.items():
            query = re.sub(rf"\b{re.escape(src)}\b", dst, query)
        for src, dst in _EXTRA_ALIASES.items():
            query = re.sub(rf"\b{re.escape(src)}\b", dst, query)
        query = re.sub(r"\b\d+[a-z]*\b", " ", query)
        query = re.sub(r"\s+", " ", query).strip()
        return query

    def _tokens(self, text: str) -> list[str]:
        toks = [tok for tok in text.split() if len(tok) >= 3 and tok not in _STOP_TOKENS]
        return toks

    def _candidate_ids(self, query: str, q_tokens: list[str]) -> tuple[set[int], dict[int, int]]:
        postings: list[set[int]] = []
        for tok in q_tokens:
            post = self.token_index.get(tok)
            if post:
                postings.append(post)
                continue
            # Fuzzy rescue for OCR typos / multilingual near-forms.
            near = difflib.get_close_matches(tok, self.vocab_tokens, n=2, cutoff=0.88)
            for ntok in near:
                npost = self.token_index.get(ntok)
                if npost:
                    postings.append(npost)
        semantic_rank: dict[int, int] = {}
        semantic_ids: set[int] = set()
        if self.search_index is not None and query.strip():
            for rank, name in enumerate(self.search_index.search(query, self.semantic_top_n)):
                for idx in self.name_to_ids.get(name, []):
                    semantic_ids.add(idx)
                    prev = semantic_rank.get(idx)
                    semantic_rank[idx] = rank if prev is None else min(prev, rank)

        postings = [p for p in postings if p]
        if not postings:
            return semantic_ids, semantic_rank
        postings.sort(key=len)
        ids = set(postings[0])
        for post in postings[1:3]:
            ids &= post
            if ids:
                break
        if ids:
            ids |= semantic_ids
            return ids, semantic_rank
        ids = set()
        for post in postings[:3]:
            ids |= post
        ids |= semantic_ids
        return ids, semantic_rank

    def _anchored_candidate(self, query: str) -> str | None:
        for pattern, target in _CONCEPT_TARGETS:
            if pattern.search(query) and target in self.valid_foods:
                return target
        return None

    def propose(self, product_name: str, count: int) -> MatchProposal:
        query = self._normalize_query(product_name)
        if not query:
            return MatchProposal(product_name, count, None, "none", 0.0, 0.0, query)

        q_tokens = self._tokens(query)
        if not q_tokens:
            return MatchProposal(product_name, count, None, "none", 0.0, 0.0, query)

        anchored = self._anchored_candidate(query)
        if anchored:
            return MatchProposal(product_name, count, anchored, "high", 98.0, 98.0, query)

        # Fast path: exact normalized match.
        exact_ids = self.norm_to_ids.get(query, [])
        if exact_ids:
            idx = exact_ids[0]
            return MatchProposal(product_name, count, self.food_names[idx], "high", 99.0, 99.0, query)

        cand_ids, semantic_rank = self._candidate_ids(query, q_tokens)
        if not cand_ids:
            return MatchProposal(product_name, count, None, "none", 0.0, 0.0, query)

        scored: list[tuple[float, int]] = []
        q_set = set(q_tokens)
        for idx in cand_ids:
            name_norm = self.food_norms[idx]
            n_tokens = set(self._tokens(name_norm))
            overlap = len(q_set & n_tokens)
            if overlap == 0 and idx not in semantic_rank:
                continue
            coverage = overlap / max(len(q_set), 1)
            ratio = difflib.SequenceMatcher(None, query, name_norm).ratio()
            prefix = 1.0 if name_norm.startswith(query) or query.startswith(name_norm) else 0.0
            sem_bonus = 0.0
            rank = semantic_rank.get(idx)
            if rank is not None and self.semantic_top_n > 0:
                sem_bonus = ((self.semantic_top_n - rank) / self.semantic_top_n) * 1.5
            score = overlap + (coverage * 3.0) + (ratio * 1.2) + prefix + sem_bonus
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
        count_bonus = 0.03 * min(max(count - 1, 0), 10)

        top_rank = semantic_rank.get(best_idx)
        semantic_high = top_rank is not None and top_rank <= 2 and ratio >= 0.72

        if semantic_high or (coverage >= 1.0 and ratio >= 0.70 and (gap + count_bonus) >= 0.20):
            confidence = "high"
        elif coverage >= 0.60 and ratio >= 0.62 and (gap + count_bonus) >= 0.12:
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
        "--no-semantic",
        action="store_true",
        help="Disable embedding-based retrieval and use lexical matching only",
    )
    parser.add_argument(
        "--semantic-top-n",
        type=int,
        default=40,
        help="Number of semantic candidates to retrieve when embeddings are enabled",
    )
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
    skill = LocalRemapSkill(
        use_semantic=not args.no_semantic,
        semantic_top_n=args.semantic_top_n,
    )

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
