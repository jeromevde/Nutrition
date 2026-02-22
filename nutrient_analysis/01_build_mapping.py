"""
nutrient_analysis/01_build_mapping.py
======================================
Builds a mapping: Delhaize product name → pyfooda food entry + grams.

Pipeline:
  1. Load all Delhaize ticket CSVs from scrapers/delhaize/tickets/
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
import os, re, glob, json, time, textwrap
from pathlib import Path

import pandas as pd
from pyfooda import api
from rank_bm25 import BM25Okapi
import openai

# ── Config ────────────────────────────────────────────────────────────────────
TICKETS_DIR = Path(__file__).parent.parent / "scrapers" / "delhaize" / "tickets"
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


# ── BM25 helpers ──────────────────────────────────────────────────────────────

def _norm(name: str) -> str:
    """Normalise a name for BM25 tokenisation."""
    # Strip leading weight tokens (400G, 1.5L, 250GR …)
    name = re.sub(r'\b\d[\d,\.]*\s*[GKLgkl][GRLgrl]?\b', '', name)
    # Strip stray digits
    name = re.sub(r'\b\d+\b', '', name)
    return name.lower().strip()


def bm25_top_n(query: str, n: int = BM25_TOP_N) -> list[str]:
    """Return up to n food names ranked by BM25, filtering obvious junk."""
    results = api.find_closest_matches(query, n=n * 3)   # over-fetch then dedupe
    seen, out = set(), []
    for r in results:
        key = r.lower()
        if key not in seen:
            seen.add(key)
            out.append(r)
        if len(out) >= n:
            break
    return out


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
    3. Fall back: BM25 search on the LLM name, take top-1.
    """
    upper = llm_name.upper()
    for t in top10:
        if t.upper() == upper:
            return t
    exact = pyfooda_exact(llm_name)
    if exact:
        return exact
    fallback = bm25_top_n(llm_name, n=1)
    return fallback[0] if fallback else llm_name


# ── LLM batch matching ────────────────────────────────────────────────────────

SYSTEM_PROMPT = textwrap.dedent("""\
    You are a nutrition database assistant. You receive batches of product names
    from Belgian/French Delhaize grocery receipts (French-speaking Belgium) and
    must map each one to the best USDA FoodData Central food entry.

    CONTEXT: Names are abbreviated French/English grocery labels.
    Key French terms: PATE = pasta (NOT pâté), POULET = chicken, SAUMON = salmon,
    OEUFS = eggs, LAIT = milk, BEURRE = butter, FROMAGE = cheese, BOEUF = beef,
    PORC = pork, VEAU = veal, DLL/DELH = Delhaize brand, BIO = organic.

    For EACH item respond with one of:
      • action "ignore" – NOT a real food product:
        discount lines (21EME A 1/2 PRIX, 2+1 GRATUIT, NUTRI-BOOST),
        quantity placeholders (2 x, 4 x, 0,600 Kg x),
        bare barcodes, fees, bag charges, negative-price lines.
      • action "match" – choose the best matching food:
        STRONGLY PREFER to chose from the provided candidates list.
        Only suggest a different generic USDA name (e.g. "Hazelnut spread"
        for NUTELLA) when NONE of the candidates are appropriate.
        Also extract the weight in grams from the product name:
          400G → 400, 1.5KG → 1500, 0,600 Kg → 600, 1L → 1000.
        Set grams to null if no weight is mentioned.

    Respond ONLY with a valid JSON array – no markdown fences, no explanation:
    [
      {"id": <int>, "action": "match", "pyfooda_name": "<food name>", "grams": <float|null>},
      {"id": <int>, "action": "ignore"},
      ...
    ]
""")


def call_llm_batch(items: list[dict], client: openai.OpenAI) -> list[dict]:
    """
    items = [{"id": int, "name": str, "candidates": [str, ...]}, ...]
    Returns list of {"id", "action", "pyfooda_name"?, "grams"?}
    """
    user_msg = json.dumps({"items": items}, ensure_ascii=False)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = client.chat.completions.create(
                model=LLM_MODEL,
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

    print(f"\nBuilding BM25 index for {len(unique_names)} names…")

    # Pre-compute BM25 top-10 for all names at once
    name_to_top10: dict[str, list[str]] = {}
    for i, name in enumerate(unique_names, 1):
        query = _norm(name)
        name_to_top10[name] = bm25_top_n(query) if query.strip() else []
        if i % 100 == 0:
            print(f"  BM25: {i}/{len(unique_names)}")

    print(f"\nSending {len(unique_names)} items to LLM in batches of {LLM_BATCH}…")

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
        print(f"  Batch {batch_start // LLM_BATCH + 1} "
              f"({batch_start + 1}–{min(batch_start + LLM_BATCH, len(indexed))}) …", end=" ", flush=True)

        llm_out = call_llm_batch(items_payload, client)
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
                    "grams":         grams,
                })

        print("done")

    return all_results


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise EnvironmentError("Set OPENROUTER_API_KEY before running.")

    client = openai.OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
        timeout=120,
        max_retries=2,
    )

    # ── 1. Load tickets ───────────────────────────────────────────────────────
    print("=" * 60)
    print("Step 1 – Loading tickets")
    print("=" * 60)
    raw = load_all_tickets()
    print(f"Raw rows: {len(raw):,}  |  Tickets: {raw['source_file'].nunique()}")
    print(f"Date range: {raw['date'].min().date()} → {raw['date'].max().date()}")

    purchases = filter_purchases(raw)
    print(f"After filtering: {len(purchases):,} rows  |  "
          f"Unique names: {purchases['product_name'].nunique()}")

    # ── 2. Load existing mapping (incremental) ────────────────────────────────
    if MAPPING_CSV.exists():
        existing_df = pd.read_csv(MAPPING_CSV)
        existing_names = set(existing_df['delhaize_name'].str.upper())
        print(f"\nExisting mapping has {len(existing_df)} entries.")
    else:
        existing_df = pd.DataFrame()
        existing_names = set()

    # ── 3. BM25 + LLM mapping ─────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("Step 2 – Loading pyfooda BM25 index")
    print("=" * 60)
    api.ensure_data_loaded()
    print(f"pyfooda: {len(api._food_names):,} food names indexed.")

    unique_names = sorted(purchases['product_name'].unique())
    new_rows = build_mapping(unique_names, client, existing_names)

    if new_rows:
        new_df = pd.DataFrame(new_rows)
        mapping_df = pd.concat([existing_df, new_df], ignore_index=True) if not existing_df.empty else new_df
    else:
        mapping_df = existing_df
        print("No new names to map.")

    mapping_df.to_csv(MAPPING_CSV, index=False)

    matched   = (mapping_df['action'] == 'match').sum()
    ignored   = (mapping_df['action'] == 'ignore').sum()
    print(f"\nMapping saved → {MAPPING_CSV}")
    print(f"  matched: {matched}  ignored: {ignored}  "
          f"({matched / len(mapping_df) * 100:.1f}% match rate)")

    # ── 4. Enrich purchases ───────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("Step 3 – Enriching purchase rows")
    print("=" * 60)

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
    print(f"Purchases enriched: {len(enriched):,} rows  |  "
          f"{n_matched:,} with a pyfooda match ({n_matched / len(enriched) * 100:.1f}%)")
    print(f"Saved → {PURCHASES_CSV}")
    print("\nDone. Run 02_nutrition_report.py next.")


if __name__ == "__main__":
    main()
