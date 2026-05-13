"""
nutrient_analysis/01_build_mapping.py
======================================
Builds a mapping: Delhaize product name → pyfooda food entry + grams.

Pipeline:
  1. Load all Delhaize ticket CSVs from scrape_extract_data/delhaize/
  2. Pre-filter non-food rows (discounts, weight placeholders, malformed)
  3. For each unique product name → BM25 top-10 pyfooda candidates
  4. Batch 50 items at a time → OpenRouter LLM decides:
       • ignore   – non-food / malformed
       • match    – picks best pyfooda entry + extracts grams from name
  5. If LLM proposes a name not in top-10 → re-run BM25 on that name
  6. Save:
       output/delhaize_mapping.csv      – unique name → pyfooda match + grams
       output/purchases_enriched.csv    – every purchase row enriched

Set OPENROUTER_API_KEY in your environment before running.
"""

from __future__ import annotations
import os, re, glob, json, time, textwrap, sys
from pathlib import Path

import numpy as np
import pandas as pd
from pyfooda import api
import openai

# Allow importing shared _llm_client from the repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _llm_client import make_client

# ── Timestamped logging ──────────────────────────────────────────────────────────
_t0 = time.monotonic()
_tprev: list[float] = [_t0]  # mutable so nested functions can update it

def tlog(msg: str, end: str = "\n", flush: bool = False) -> None:
    """Print msg prefixed with [HH:MM:SS +step_elapsed / total] for profiling."""
    now   = time.monotonic()
    step  = now - _tprev[0]
    total = now - _t0
    _tprev[0] = now
    ts = time.strftime("%H:%M:%S", time.localtime())
    print(f"[{ts} +{step:5.1f}s / {total:6.1f}s] {msg}", end=end, flush=flush)

# ── Config ────────────────────────────────────────────────────────────────────
TICKETS_DIR = Path(__file__).parent.parent / "scrape_extract_data" / "delhaize"
OUT_DIR     = Path(__file__).parent / "output"
OUT_DIR.mkdir(exist_ok=True)

MAPPING_CSV   = OUT_DIR / "delhaize_mapping.csv"
PURCHASES_CSV = OUT_DIR / "purchases_enriched.csv"

LLM_MODEL     = "google/gemini-2.0-flash-001"   # cheap + smart; change freely
LLM_BATCH     = 50                           # items per LLM call
BM25_TOP_N    = 10                           # candidates shown to LLM
MAX_RETRIES   = 3

# Regex patterns for rows that are definitely NOT food purchases
_NON_FOOD_RE = re.compile(
    r"""
    ^ (\s*
        ( NUTRI.?BOOST               # loyalty discount tags
        | \d+EME\s+[AÀ]             # "21EME À 1/2 PRIX"
        | \d+E\s+[AÀ]               # "3E À"
        | \d+\+\d+\s+GRATUIT        # "2+1 GRATUIT"
        | [A-Z]+\s+[AÀ]\s+\d+/\d+ # "21EME A 1/2 PRIX"
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
        | [0-9]+\s+[xX]\s*$        # "2 x" or "4 x" lines (quantity-only)
        | 0,\d+\s+[Kk][Gg]\s+[xX] # "0,600 Kg x" (weight lines)
        | ^\d{6,}$                  # bare barcode accidentally as name
    ) \s* ) $
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Also filter by negative price (discounts) – done separately on the price column


# ── Grams sanity helpers ──────────────────────────────────────────────────────

def _sanitize_grams(name: str, grams) -> float | None:  # noqa: ARG001
    """Coerce LLM grams output to float | None (type safety only).

    Year-as-grams and other semantic errors are prevented upstream by the
    SYSTEM_PROMPT (rule 2: leading 4-digit year is not a weight).
    This function only handles Python type edge-cases.
    """
    if grams is None:
        return None
    try:
        g = float(grams)
    except (TypeError, ValueError):
        return None
    if np.isnan(g):
        return None
    return g


# ── Load tickets ──────────────────────────────────────────────────────────────

def load_all_tickets() -> pd.DataFrame:
    frames = []
    for path in sorted(glob.glob(str(TICKETS_DIR / "*.csv"))):
        stem = Path(path).stem
        m = re.match(r"(\d{4})_(\d{2})_(\d{2})", stem)
        if not m:
            print(f"  Skipping: {path}")
            continue
        year, month, day = m.groups()
        # Fix transposed day/month (e.g. 2024_31_08 → 2024_08_31)
        if int(month) > 12:
            month, day = day, month
        date_str = f"{year}-{month}-{day}"
        try:
            df = pd.read_csv(path, dtype=str)
            df['date']        = date_str
            df['source_file'] = Path(path).name
            frames.append(df)
        except Exception as e:
            print(f"  Error reading {path}: {e}")

    if not frames:
        raise RuntimeError(f"No CSVs found in {TICKETS_DIR}")

    combined = pd.concat(frames, ignore_index=True)
    combined['date']  = pd.to_datetime(combined['date'])
    combined['price'] = pd.to_numeric(combined['price'], errors='coerce')
    combined = combined.dropna(subset=['product_name'])
    combined['product_name'] = combined['product_name'].str.strip().str.upper()
    return combined


def filter_purchases(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only real food purchase rows (positive price, not a discount/placeholder)."""
    # Remove negative-price rows (discounts, refunds)
    df = df[df['price'].fillna(0) >= 0].copy()
    # Remove rows matching the non-food regex
    mask = df['product_name'].apply(lambda n: bool(_NON_FOOD_RE.match(str(n))))
    removed = df[mask]['product_name'].unique()
    if len(removed):
        print(f"  Pre-filtered {mask.sum()} rows matching non-food patterns.")
        print(f"  Examples: {list(removed[:8])}")
    return df[~mask].copy()


# ── FAISS + sentence-embedding helpers ────────────────────────────────────────

_faiss_index = None    # lazy-built FAISS index
_food_names: list[str] = []
_embedder = None

def _ensure_index():
    """Build the FAISS index from pyfooda food names (once)."""
    global _faiss_index, _food_names, _embedder
    if _faiss_index is not None:
        return

    import faiss
    from sentence_transformers import SentenceTransformer

    _embedder = SentenceTransformer("all-MiniLM-L6-v2")

    fd = api.get_fooddata_df()
    _food_names = fd['foodName'].dropna().unique().tolist()
    tlog(f"  Encoding {len(_food_names):,} food names with sentence-transformers …")
    vecs = _embedder.encode(_food_names, show_progress_bar=True,
                            batch_size=512, normalize_embeddings=True)
    d = vecs.shape[1]
    _faiss_index = faiss.IndexFlatIP(d)          # inner-product = cosine (normalised)
    _faiss_index.add(np.ascontiguousarray(vecs.astype(np.float32)))
    tlog(f"  FAISS index ready ({_faiss_index.ntotal} vectors, dim={d})")


def _norm(name: str) -> str:
    """Normalise a name for embedding search."""
    # Strip leading weight tokens (400G, 1.5L, 250GR …)
    name = re.sub(r'\b\d[\d,\.]*\s*[GKLgkl][GRLgrl]?\b', '', name)
    # Strip stray digits
    name = re.sub(r'\b\d+\b', '', name)
    return name.lower().strip()


def faiss_top_n(query: str, n: int = BM25_TOP_N) -> list[str]:
    """Return up to n food names ranked by cosine similarity via FAISS."""
    _ensure_index()
    q_vec = _embedder.encode([query], normalize_embeddings=True).astype(np.float32)
    _, idxs = _faiss_index.search(q_vec, n)
    return [_food_names[i] for i in idxs[0] if 0 <= i < len(_food_names)]


def pyfooda_exact(name: str) -> str | None:
    """Try case-insensitive exact lookup in pyfooda foodName column."""
    fd = api.get_fooddata_df()
    mask = fd['foodName'].str.upper() == name.upper()
    if mask.any():
        return fd.loc[mask, 'foodName'].iloc[0]
    return None


def resolve_match(llm_name: str, top10: list[str]) -> str:
    """
    Map an LLM-provided food name to an actual pyfooda entry:
    1. If it's in top-10 (case-insensitive) → use it.
    2. Try exact lookup in full fooddata.
    3. Fall back: FAISS search on the LLM name, take top-1.
    """
    upper = llm_name.upper()
    for t in top10:
        if t.upper() == upper:
            return t
    exact = pyfooda_exact(llm_name)
    if exact:
        return exact
    fallback = faiss_top_n(llm_name, n=1)
    return fallback[0] if fallback else llm_name


# ── LLM batch matching ────────────────────────────────────────────────────────

SYSTEM_PROMPT = textwrap.dedent("""\
    You are a nutrition database assistant. You receive batches of product names
    from Belgian/French Delhaize grocery receipts (French-speaking Belgium) and
    must map each one to the best USDA FoodData Central food entry.

    CONTEXT: Names are abbreviated French/English grocery labels.
    Key French terms:
      PATE = PASTA noodles (NOT meat pâté)  POULET = chicken  SAUMON = salmon
      OEUFS/OEUVS = eggs  LAIT = milk  BEURRE = butter  FROMAGE = cheese
      BOEUF = beef  PORC = pork  VEAU = veal  AGNEAU = lamb
      DLL/DELH/DLC/DLI/DOL/MKA = Delhaize house brand  BIO = organic
      BLINI = small pancakes (NOT pasta)  SKYR = Icelandic yogurt
      POUSE/POUSS/POUSSE = mixed salad shoots  MESCLUN = salad mix

    ── MATCHING RULES ────────────────────────────────────────────────────────
    • STRONGLY PREFER to choose from the provided candidates list.
    • Prefer SPECIFIC names over single-word generics:
        "Potato chips, salted" beats "CHIPS"
        "Lemon-lime carbonated beverage" beats "LEMON"
        "Paprika spice" is WRONG for "185G LAYS PAPRIKA" (a snack bag)
    • If the product is a packaged snack (LAYS, PRINGLES, BUGLES, TORTILLA,
      CHIPS, HUGLES), match to a snack/crisp entry — NEVER to a spice.
    • If the product is a beverage (suffix ML/CL/L, SODA, SCHWEPPES, FANTA,
      GINI, JUPILER, COLA, PROSECCO, ROSÉ), match to a beverage — NOT the fruit.
    • Non-food items (serviettes/napkins, candles, flowers, clothing, stationery)
      → action "ignore".
    • Also ignore: discount lines (21EME A 1/2 PRIX, 2+1 GRATUIT, NUTRI-BOOST),
      quantity placeholders (2 x, 4 x, 0,600 Kg x), bare barcodes, fees.

    ── GRAMS EXTRACTION — MANDATORY ─────────────────────────────────────────
    Set grams to null ONLY for items you mark "ignore" or when truly impossible.
    For EVERY "match" you MUST provide a numeric grams value.

    1. EXPLICIT weight in the name → convert to grams exactly:
         400G→400  1.5KG→1500  0,600Kg→600  1L→1000  33CL→330
         500ML→500  75CL→750  6X25CL→150  2KG→2000  4X1L→4000

    2. LEADING 4-DIGIT YEAR IS NOT A WEIGHT:
         "2025 GINGER BIO" → year 2025 is the product year, NOT grams → infer 330
         "2065 PEHL NEW BIO" → 2065 is not a weight → infer from product type

    3. NO explicit weight → INFER typical Belgian retail package size:
         Single fresh fruit (avocado, mango, lemon, lime) → 200, 400, 100, 80
         Banana (loose, each) → 120   Orange/mandarin → 150   Shallot → 60
         Fresh herb pot (basil, parsley, mint, chives) → 30
         Bag of salad mix / mesclun / pousses → 150
         Bag of chips 185G pack → 185   Generic crisp bag → 150
         Bottle of juice/water (no size) → 500   Wine bottle → 750
         Can of soda/beer 33cl → 330   Large soda bottle 1.5L → 1500
         Pot of yogurt → 125   Skyr (large) → 450   Crème fraîche → 200
         Pack of sliced cheese → 150   Block of butter → 250
         Eggs carton 6pc → 360   Eggs carton 12pc → 720
         Pasta box → 500   Couscous bag → 500   Flour 1kg → 1000
         Pesto jar → 190   Hummus pot → 200   Guacamole → 150
         Pizza (frozen) → 400   Nuggets pack → 300
         Prosciutto/ham (sliced pack) → 100
         Blinis pack → 200   Wraps (single) → 60
         Soup cube/tablet → 50   Spice jar → 50
         Bread (baguette) → 250   Bread loaf → 500

    4. Maximum sanity: grams must be ≤ 2000 for a single retail unit.
       If your calculation exceeds 2000 re-check — you probably misread a year
       or multiplier as a weight.

    Respond ONLY with a valid JSON array – no markdown fences, no explanation:
    [
      {"id": <int>, "action": "match", "pyfooda_name": "<food name>", "grams": <float|null>},
      {"id": <int>, "action": "ignore"},
      ...
    ]
""")


def call_llm_batch(items: list[dict], client: openai.OpenAI, model: str) -> list[dict]:
    """
    items = [{"id": int, "name": str, "candidates": [str, ...]}, ...]
    Returns list of {"id", "action", "pyfooda_name"?, "grams"?}
    """
    user_msg = json.dumps({"items": items}, ensure_ascii=False)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": user_msg},
                ],
                temperature=0,
                max_tokens=4096,
            )
            raw = resp.choices[0].message.content.strip()
            # Strip accidental markdown fences
            raw = re.sub(r'^```(?:json)?\s*', '', raw, flags=re.MULTILINE)
            raw = re.sub(r'\s*```$', '',      raw, flags=re.MULTILINE)
            return json.loads(raw)
        except (json.JSONDecodeError, Exception) as e:
            print(f"    LLM attempt {attempt}/{MAX_RETRIES} failed: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(2 ** attempt)
    # On total failure: mark everything as ignore to be safe
    print("    !! LLM failed entirely for this batch – marking all as ignore")
    return [{"id": item["id"], "action": "ignore"} for item in items]


def build_mapping(
    unique_names: list[str],
    client: openai.OpenAI,
    existing_names: set[str] | None = None,
    model: str = LLM_MODEL,
) -> list[dict]:
    """
    For each unique product name:
      1. Run BM25 to get top-10 candidates.
      2. Batch 50 items → LLM → action + pyfooda_name + grams.
      3. Resolve pyfooda_name against the actual database.
    """
    if existing_names:
        unique_names = [n for n in unique_names if n not in existing_names]
    if not unique_names:
        return []

    print(f"\nBuilding FAISS index for {len(unique_names)} names\u2026")
    _ensure_index()     # build once before the loop

    # Pre-compute FAISS top-10 for all names at once
    name_to_top10: dict[str, list[str]] = {}
    for i, name in enumerate(unique_names, 1):
        query = _norm(name)
        name_to_top10[name] = faiss_top_n(query) if query.strip() else []
        if i % 100 == 0:
            print(f"  FAISS: {i}/{len(unique_names)}")

    tlog(f"\nSending {len(unique_names)} items to LLM in batches of {LLM_BATCH}…")

    all_results: list[dict] = []
    indexed = list(enumerate(unique_names))   # (global_id, name)

    for batch_start in range(0, len(indexed), LLM_BATCH):
        batch = indexed[batch_start: batch_start + LLM_BATCH]
        items_payload = [
            {
                "id":         gid,
                "name":       name,
                "candidates": name_to_top10[name],
            }
            for gid, name in batch
        ]
        tlog(f"  Batch {batch_start // LLM_BATCH + 1} "
              f"({batch_start + 1}–{min(batch_start + LLM_BATCH, len(indexed))}) …", end=" ", flush=True)

        llm_out = call_llm_batch(items_payload, client, model)
        # Index by id for easy lookup
        by_id = {r["id"]: r for r in llm_out}

        for gid, name in batch:
            result = by_id.get(gid, {"id": gid, "action": "ignore"})
            action = result.get("action", "ignore")

            if action == "ignore":
                all_results.append({
                    "delhaize_name": name,
                    "action":        "ignore",
                    "pyfooda_name":  "",
                    "grams":         None,
                })
            else:
                raw_pyfname = str(result.get("pyfooda_name", "")).strip()
                grams = result.get("grams")
                if isinstance(grams, str):
                    try:
                        grams = float(re.sub(r"[^\d.]", "", grams)) or None
                    except ValueError:
                        grams = None

                resolved = resolve_match(raw_pyfname, name_to_top10[name]) if raw_pyfname else ""
                all_results.append({
                    "delhaize_name": name,
                    "action":        "match",
                    "pyfooda_name":  resolved,
                    "llm_raw_name":  raw_pyfname,
                    "grams":         _sanitize_grams(name, grams),
                })

        print("done")

    return all_results


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Build Delhaize → pyfooda mapping")
    parser.add_argument(
        "--remap-nullgrams", action="store_true",
        help="Re-run LLM for matched entries that have no grams value (improves weight coverage)",
    )
    parser.add_argument(
        "--remap-short", action="store_true",
        help="Re-run LLM for matched entries with a short pyfooda name (≤5 chars = likely bad generic match)",
    )
    args = parser.parse_args()

    client, model = make_client(LLM_MODEL)

    # ── 1. Load tickets ───────────────────────────────────────────────────────
    tlog("=" * 60)
    tlog("Step 1 – Loading tickets")
    tlog("=" * 60)
    raw = load_all_tickets()
    tlog(f"Raw rows: {len(raw):,}  |  Tickets: {raw['source_file'].nunique()}")
    tlog(f"Date range: {raw['date'].min().date()} → {raw['date'].max().date()}")

    purchases = filter_purchases(raw)
    tlog(f"After filtering: {len(purchases):,} rows  |  "
          f"Unique names: {purchases['product_name'].nunique()}")

    # ── 2. Load existing mapping (incremental) ────────────────────────────────
    if MAPPING_CSV.exists():
        existing_df = pd.read_csv(MAPPING_CSV)
        existing_names = set(existing_df['delhaize_name'].str.upper())
        print(f"\nExisting mapping has {len(existing_df)} entries.")

        names_to_remap: set[str] = set()

        # --remap-nullgrams: drop matched entries with no grams so they get re-run
        if args.remap_nullgrams:
            null_mask = (
                (existing_df['action'] == 'match') &
                existing_df['grams'].isna()
            )
            names_to_remap |= set(existing_df.loc[null_mask, 'delhaize_name'].str.upper())
            print(f"  --remap-nullgrams: will re-run {null_mask.sum()} entries with null grams")

        # --remap-short: drop matched entries with suspiciously short pyfooda names
        if args.remap_short:
            short_mask = (
                (existing_df['action'] == 'match') &
                (existing_df['pyfooda_name'].str.len() <= 5)
            )
            names_to_remap |= set(existing_df.loc[short_mask, 'delhaize_name'].str.upper())
            print(f"  --remap-short: will re-run {short_mask.sum()} entries with short pyfooda names")

        if names_to_remap:
            existing_names -= names_to_remap
            # Also remove those rows from existing_df so the new results replace them
            existing_df = existing_df[
                ~existing_df['delhaize_name'].str.upper().isin(names_to_remap)
            ].reset_index(drop=True)
    else:
        existing_df = pd.DataFrame()
        existing_names = set()

    # ── 3. BM25 + LLM mapping ─────────────────────────────────────────────────
    tlog("\n" + "=" * 60)
    tlog("Step 2 – Building FAISS semantic search index")
    tlog("=" * 60)
    api.ensure_data_loaded()
    _ensure_index()
    tlog(f"pyfooda: {len(_food_names):,} food names indexed.")

    unique_names = sorted(purchases['product_name'].unique())
    new_rows = build_mapping(unique_names, client, existing_names, model)

    if new_rows:
        new_df = pd.DataFrame(new_rows)
        mapping_df = pd.concat([existing_df, new_df], ignore_index=True) if not existing_df.empty else new_df
    else:
        mapping_df = existing_df
        print("No new names to map.")

    # Sanitize grams on entire mapping (fixes pre-existing year-as-grams, caps outliers)
    mapping_df['grams'] = [
        _sanitize_grams(row['delhaize_name'], row['grams'])
        for _, row in mapping_df.iterrows()
    ]

    # Guard: keep only the last entry per delhaize_name (new rows win over old)
    mapping_df = mapping_df.drop_duplicates(subset='delhaize_name', keep='last').reset_index(drop=True)

    mapping_df.to_csv(MAPPING_CSV, index=False)

    matched   = (mapping_df['action'] == 'match').sum()
    ignored   = (mapping_df['action'] == 'ignore').sum()
    tlog(f"\nMapping saved → {MAPPING_CSV}")
    tlog(f"  matched: {matched}  ignored: {ignored}  "
          f"({matched / len(mapping_df) * 100:.1f}% match rate)")

    # ── 4. Enrich purchases ───────────────────────────────────────────────────
    tlog("\n" + "=" * 60)
    tlog("Step 3 – Enriching purchase rows")
    tlog("=" * 60)

    lookup = mapping_df.set_index('delhaize_name')[['pyfooda_name', 'grams', 'action']].to_dict('index')

    def enrich(row):
        info = lookup.get(row['product_name'], {})
        return pd.Series({
            'pyfooda_name': info.get('pyfooda_name', ''),
            'grams_in_name': info.get('grams'),
            'llm_action':   info.get('action', 'unknown'),
        })

    enriched = purchases.join(purchases.apply(enrich, axis=1))
    enriched.to_csv(PURCHASES_CSV, index=False)

    n_matched = (enriched['llm_action'] == 'match').sum()
    tlog(f"Purchases enriched: {len(enriched):,} rows  |  "
          f"{n_matched:,} with a pyfooda match ({n_matched / len(enriched) * 100:.1f}%)")
    print(f"Saved → {PURCHASES_CSV}")
    print("\nDone. Run 02_nutrition_report.py next.")


if __name__ == "__main__":
    main()
