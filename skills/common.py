"""Shared helpers for repo-local LLM skills."""

from __future__ import annotations

import base64
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
CARREFOUR_DATA_DIR = DATA_DIR / "carrefour"
COLRUYT_DATA_DIR = DATA_DIR / "colruyt"
DELHAIZE_DATA_DIR = DATA_DIR / "delhaize"
SESSIONS_DATA_DIR = DATA_DIR / "sessions"
DELHAIZE_SCRAPER_DIR = DELHAIZE_DATA_DIR
OUTPUT_DIR = DATA_DIR
DEFAULT_REPORT = OUTPUT_DIR / "nutrition_report.html"
DEFAULT_MAPPING = OUTPUT_DIR / "delhaize_mapping.csv"
DEFAULT_PURCHASES = OUTPUT_DIR / "purchases_enriched.csv"
DEFAULT_MATCHER_MODEL = "google/gemini-2.0-flash-001"
DEFAULT_OCR_MODEL = "qwen/qwen-2-vl-7b-instruct"


def get_pyfooda_foods_df():
    """Return a normalized pyfooda foods DataFrame across API variants.

    Ensures the returned frame has a ``display_name`` column.
    """
    from pyfooda import api

    api.ensure_data_loaded()

    if hasattr(api, "get_ingredients_df"):
        foods = api.get_ingredients_df().copy()
    elif hasattr(api, "get_fooddata_df"):
        foods = api.get_fooddata_df().copy()
    elif hasattr(api, "foods_df"):
        foods = api.foods_df.copy()
    else:
        raise AttributeError("pyfooda.api has no supported foods dataframe accessor")

    if "display_name" not in foods.columns:
        if "foodName" in foods.columns:
            foods = foods.rename(columns={"foodName": "display_name"})
        else:
            raise KeyError("Expected one of display_name or foodName in pyfooda foods dataframe")
    return foods


def ensure_repo_root_on_path() -> None:
    """Allow skills to import root-level helpers when run as modules."""
    root = str(ROOT_DIR)
    if root not in sys.path:
        sys.path.insert(0, root)


def batched(items: Sequence[Any], batch_size: int) -> Iterable[Sequence[Any]]:
    if batch_size <= 0:
        raise ValueError("batch_size must be > 0")
    for start in range(0, len(items), batch_size):
        yield items[start:start + batch_size]


def parse_json_response(text: str) -> Any:
    """Parse JSON returned by an LLM, tolerating markdown fences."""
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = min(
            [idx for idx in (cleaned.find("["), cleaned.find("{")) if idx >= 0],
            default=-1,
        )
        end = max(cleaned.rfind("]"), cleaned.rfind("}"))
        if start >= 0 and end > start:
            return json.loads(cleaned[start:end + 1])
        raise


def llm_json(client: Any, model: str, system_prompt: str, payload: Any, *, max_tokens: int = 4096) -> Any:
    """Send a JSON-oriented chat request and parse the JSON response."""
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        temperature=0,
        max_tokens=max_tokens,
    )
    return parse_json_response(response.choices[0].message.content or "")


def load_report_data(report_path: Path | str = DEFAULT_REPORT) -> dict[str, Any]:
    """Extract the embedded DATA object from nutrition_report.html."""
    report_text = Path(report_path).read_text(encoding="utf-8")
    match = re.search(r"const DATA=(.*?);\nlet state=", report_text, re.S)
    if not match:
        raise ValueError(f"Could not find embedded DATA object in {report_path}")
    return json.loads(match.group(1))


def image_to_data_url(image_path: Path | str) -> str:
    path = Path(image_path)
    suffix = path.suffix.lower().lstrip(".") or "jpeg"
    mime = "jpeg" if suffix in {"jpg", "jpeg"} else suffix
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/{mime};base64,{encoded}"


_WEIGHT_RE = re.compile(r"\b\d+[\d,.]*\s*(?:G|GR|KG|ML|CL|L|PC|PCS)\b", re.I)
_NON_WORD_RE = re.compile(r"[^A-Z0-9]+")

# Light multilingual aliasing for FR/NL grocery OCR labels.
# Keep this token-level and conservative: map obvious food words only.
_TOKEN_ALIASES: dict[str, str] = {
    "EPINARD": "spinach",
    "EPINARDS": "spinach",
    "AGNEAU": "lamb",
    "BOEUF": "beef",
    "BEEF": "beef",
    "CARPACCIO": "carpaccio",
    "ROSBIF": "roast beef",
    "STOKBROOD": "baguette",
    "BAGUETTE": "baguette",
    "PENNE": "penne",
    "HOUMOUS": "hummus",
    "HUMMUS": "hummus",
    "NOISETTES": "cut",
    "JEUNES": "young",
    "POUSSES": "shoots",
}


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_food_query(name: str) -> str:
    """Normalize receipt text before semantic search."""
    name = _strip_accents(str(name)).upper()
    name = _WEIGHT_RE.sub(" ", name)
    for src, dst in _TOKEN_ALIASES.items():
        name = re.sub(rf"\b{re.escape(src)}\b", f" {dst.upper()} ", name)
    name = _NON_WORD_RE.sub(" ", name)
    return " ".join(name.lower().split())


@dataclass
class FoodSearchIndex:
    food_names: list[str]
    embedder: Any
    index: Any

    def search(self, query: str, top_n: int = 10) -> list[str]:
        import numpy as np

        if not query.strip():
            return []
        query_vector = self.embedder.encode([query], normalize_embeddings=True).astype(np.float32)
        _, indexes = self.index.search(query_vector, top_n)
        return [self.food_names[index] for index in indexes[0] if 0 <= index < len(self.food_names)]


def build_food_search_index(model_name: str = "all-MiniLM-L6-v2") -> FoodSearchIndex:
    """Build a FAISS semantic index over pyfooda ingredient display names."""
    import faiss
    import numpy as np
    from sentence_transformers import SentenceTransformer

    ingredients = get_pyfooda_foods_df()
    food_names = ingredients["display_name"].dropna().drop_duplicates().astype(str).tolist()
    embedder = SentenceTransformer(model_name)
    vectors = embedder.encode(
        food_names,
        show_progress_bar=True,
        batch_size=512,
        normalize_embeddings=True,
    )
    vectors = np.ascontiguousarray(vectors.astype(np.float32))
    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)
    return FoodSearchIndex(food_names=food_names, embedder=embedder, index=index)
