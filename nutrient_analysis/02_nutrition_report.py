"""
nutrient_analysis/02_nutrition_report.py
=========================================
Reads purchases_enriched.csv + delhaize_mapping.csv, computes per-trip nutrient
contributions from pyfooda (per-100g values × grams purchased), scales each
basket to a 2500 kcal reference, then generates:

  output/nutrition_yearly.csv   – yearly averages vs DRV
  output/nutrition_pertrip.csv  – every trip's scaled nutrients
  output/nutrition_report.html  – full interactive HTML report

Nutrient values in pyfooda are PER 100g (USDA standard).
Scaling: nutrients are multiplied by (2500 / basket_energy) so every basket
is evaluated at the same 2500 kcal family daily reference before comparison
to DRVs.
"""

from __future__ import annotations
import re
from pathlib import Path

import numpy as np
import pandas as pd
from pyfooda import api

# ── Paths ─────────────────────────────────────────────────────────────────────
OUT_DIR       = Path(__file__).parent / "output"
PURCHASES_CSV = OUT_DIR / "purchases_enriched.csv"
MAPPING_CSV   = OUT_DIR / "delhaize_mapping.csv"
REPORT_HTML   = OUT_DIR / "nutrition_report.html"
REPORT_YEARLY = OUT_DIR / "nutrition_yearly.csv"
REPORT_TRIPS  = OUT_DIR / "nutrition_pertrip.csv"

FAMILY_KCAL   = 2500          # reference daily energy for scaling
DEFAULT_GRAMS = 100           # fallback when no weight info at all

KEY_NUTRIENTS = [
    "Energy",
    "Protein", "Carbohydrate", "Fiber", "Sugars, Total", "Total fat",
    "Fatty acids, total saturated", "Cholesterol",
    "Calcium", "Iron", "Magnesium", "Potassium", "Sodium", "Zinc",
    "Vitamin A, RAE", "Vitamin C", "Vitamin D (D2 + D3)",
    "Vitamin B-12", "Folate, total", "Thiamin", "Riboflavin",
]

# ── Load pyfooda data ─────────────────────────────────────────────────────────

def load_pyfooda() -> tuple[pd.DataFrame, dict[str, float], dict[str, str]]:
    api.ensure_data_loaded()
    foods_df = api.get_fooddata_df()
    # De-duplicate: keep first occurrence per foodName (prefer sr_legacy/foundation)
    priority = {"foundation_food": 0, "sr_legacy_food": 1, "survey_fndds_food": 2,
                "sub_sample_food": 3, "agricultural_acquisition": 4, "branded_food": 5}
    foods_df = foods_df.copy()
    foods_df['_prio'] = foods_df['data_type'].map(priority).fillna(99)
    foods_df = (foods_df
                .sort_values(['foodName', '_prio'])
                .drop_duplicates('foodName', keep='first')
                .set_index('foodName'))

    # DRV
    drv_df = api.get_drv_df()
    drv: dict[str, float] = {}
    units: dict[str, str] = {}
    for _, row in drv_df.iterrows():
        n = row['nutrientName']
        if n not in drv and pd.notna(row.get('drv')):
            drv[n] = float(row['drv'])
        if n not in units:
            units[n] = str(row.get('unit_name', ''))

    return foods_df, drv, units


# ── Compute nutrients per purchase row ────────────────────────────────────────

def nutrient_contribution(
    pyfooda_name: str,
    grams: float | None,
    foods_df: pd.DataFrame,
    nutrient_cols: list[str],
) -> dict[str, float]:
    """
    Return {nutrient: value} for a single purchase.
    Value = (grams / 100) × per_100g_value.
    """
    if not pyfooda_name or pyfooda_name not in foods_df.index:
        return {}

    row = foods_df.loc[pyfooda_name]

    if grams is None:
        # Use pyfooda portion_gram_weight if available, else DEFAULT_GRAMS
        pw = row.get("portion_gram_weight", np.nan)
        grams = float(pw) if pd.notna(pw) and float(pw) > 0 else DEFAULT_GRAMS

    scale = grams / 100.0
    result: dict[str, float] = {}
    for col in nutrient_cols:
        val = row.get(col, np.nan)
        if pd.notna(val):
            result[col] = float(val) * scale
    return result


# ── Per-trip aggregation ──────────────────────────────────────────────────────

def compute_trip_nutrition(
    purchases: pd.DataFrame,
    foods_df: pd.DataFrame,
    nutrient_cols: list[str],
) -> pd.DataFrame:
    """
    For each shopping trip (source_file), sum nutrients across all matched items.
    Returns DataFrame with one row per trip.
    """
    matched = purchases[purchases['llm_action'] == 'match'].copy()
    matched['grams_in_name'] = pd.to_numeric(matched['grams_in_name'], errors='coerce')

    trip_rows = []
    for (source, date), grp in matched.groupby(['source_file', 'date']):
        totals: dict[str, float] = {col: 0.0 for col in nutrient_cols}
        n_items = 0
        n_found = 0
        for _, row in grp.iterrows():
            contrib = nutrient_contribution(
                row['pyfooda_name'],
                row['grams_in_name'] if pd.notna(row['grams_in_name']) else None,
                foods_df,
                nutrient_cols,
            )
            if contrib:
                n_found += 1
                for k, v in contrib.items():
                    totals[k] += v
            n_items += 1

        trip_row: dict = {
            'source_file': source,
            'date': date,
            'year': pd.Timestamp(date).year,
            'n_items': n_items,
            'n_found': n_found,
        }
        trip_row.update(totals)
        trip_rows.append(trip_row)

    trips_df = pd.DataFrame(trip_rows)
    trips_df['date'] = pd.to_datetime(trips_df['date'])

    # ── Scale to FAMILY_KCAL reference ────────────────────────────────────────
    # For each trip: multiply all nutrients by (FAMILY_KCAL / trip_energy)
    # so baskets of different sizes are normalised to the same energy baseline.
    energy_col = 'Energy' if 'Energy' in trips_df.columns else None
    if energy_col:
        trips_df['raw_energy'] = trips_df[energy_col]
        scale = FAMILY_KCAL / trips_df[energy_col].replace(0, np.nan)
        for col in nutrient_cols:
            if col in trips_df.columns:
                trips_df[col] = trips_df[col] * scale
        trips_df['Energy'] = FAMILY_KCAL   # by definition after scaling

    return trips_df


# ── Yearly averages ───────────────────────────────────────────────────────────

def compute_yearly(trips_df: pd.DataFrame, nutrient_cols: list[str]) -> pd.DataFrame:
    agg = trips_df.groupby('year')[nutrient_cols].mean().reset_index()
    return agg


# ── Food category breakdown ───────────────────────────────────────────────────

def category_breakdown(purchases: pd.DataFrame, foods_df: pd.DataFrame) -> pd.DataFrame:
    matched = purchases[purchases['llm_action'] == 'match'].copy()
    cat_col = 'category' if 'category' in foods_df.columns else (
              'food_category' if 'food_category' in foods_df.columns else None)
    if cat_col is None:
        return pd.DataFrame()
    cat_map = foods_df[cat_col].to_dict()
    matched['category'] = matched['pyfooda_name'].map(cat_map).fillna('Other')
    matched['year'] = pd.to_datetime(matched['date']).dt.year
    counts = matched.groupby(['year', 'category']).size().reset_index(name='count')
    totals = matched.groupby('year').size().reset_index(name='total')
    merged = counts.merge(totals, on='year')
    merged['pct'] = merged['count'] / merged['total'] * 100
    return merged.sort_values(['year', 'pct'], ascending=[True, False])


# ── HTML generation ───────────────────────────────────────────────────────────

CSS = """
<style>
:root {
  --blue:#2c7be5; --green:#28a745; --yellow:#ffc107; --red:#dc3545;
  --bg:#f5f7fa; --card:#fff; --text:#333; --muted:#888;
}
* { box-sizing: border-box; }
body { font-family:'Segoe UI',system-ui,sans-serif; background:var(--bg); color:var(--text); margin:0; }
header { background:var(--blue); color:#fff; padding:24px 40px; }
header h1 { margin:0; font-size:1.7rem; }
header p  { margin:4px 0 0; opacity:.8; font-size:.9rem; }
.wrap { max-width:1200px; margin:0 auto; padding:28px 40px; }
h2 { color:var(--blue); border-bottom:2px solid var(--blue); padding-bottom:6px; margin-top:48px; }
h3 { color:#555; margin-bottom:8px; }
.note { background:#fff8e1; border-left:4px solid var(--yellow);
        padding:12px 18px; border-radius:0 6px 6px 0; margin:16px 0; font-size:.88rem; }
.grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(190px,1fr)); gap:14px; margin:20px 0 36px; }
.card { background:var(--card); border-radius:8px; padding:18px; box-shadow:0 1px 5px rgba(0,0,0,.1); }
.card .lbl { font-size:.75rem; color:var(--muted); text-transform:uppercase; letter-spacing:.06em; }
.card .val { font-size:1.8rem; font-weight:700; color:var(--blue); }
.card .sub { font-size:.8rem; color:#666; }
table { width:100%; border-collapse:collapse; background:var(--card);
        border-radius:8px; box-shadow:0 1px 5px rgba(0,0,0,.1);
        overflow:hidden; margin-bottom:28px; }
th { background:var(--blue); color:#fff; padding:9px 14px; text-align:left; font-size:.82rem; }
td { padding:7px 14px; border-bottom:1px solid #eee; font-size:.88rem; }
tr:last-child td { border-bottom:none; }
tr:hover td { background:#f0f4ff; }
.bar-wrap { display:inline-flex; align-items:center; gap:6px; }
.bar-bg { background:#eee; border-radius:4px; height:13px; width:130px; display:inline-block; }
.bar-fg { height:100%; border-radius:4px; display:block; transition:width .3s; }
.ok   { background:var(--green); }
.low  { background:var(--yellow); }
.over { background:var(--red); }
.pct  { font-size:.82rem; font-weight:700; min-width:42px; }
.pct.ok   { color:var(--green); }
.pct.low  { color:#9a6c00; }
.pct.over { color:var(--red); }
.pill { display:inline-block; background:#e8efff; color:var(--blue);
        border-radius:12px; padding:2px 10px; margin:2px; font-size:.78rem; }
.evo-up   { color:var(--green); }
.evo-down { color:var(--red); }
.evo-flat { color:var(--muted); }
details summary { cursor:pointer; color:var(--blue); font-weight:600; margin:12px 0; }
</style>
"""

def _bar(pct: float) -> str:
    capped = min(pct, 150)
    cls = "ok" if 70 <= pct <= 120 else ("low" if pct < 70 else "over")
    w   = min(capped / 150 * 100, 100)
    return (f'<span class="bar-wrap">'
            f'<span class="bar-bg"><span class="bar-fg {cls}" style="width:{w:.0f}%"></span></span>'
            f'<span class="pct {cls}">{pct:.0f}%</span></span>')


def build_html(
    purchases: pd.DataFrame,
    trips_df: pd.DataFrame,
    yearly_df: pd.DataFrame,
    cat_df: pd.DataFrame,
    drv: dict[str, float],
    units: dict[str, str],
) -> str:

    years   = sorted(yearly_df['year'].unique())
    yr_str  = f"{min(years)}–{max(years)}" if len(years) > 1 else str(years[0])
    n_trips = len(trips_df)
    n_items = len(purchases)
    n_foods = purchases[purchases['llm_action'] == 'match']['pyfooda_name'].nunique()
    match_r = (purchases['llm_action'] == 'match').mean() * 100

    parts: list[str] = [f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8">
<title>Nutrition Report {yr_str}</title>
{CSS}
</head>
<body>
<header>
  <h1>🥗 Family Nutrition Report — {yr_str}</h1>
  <p>Based on Delhaize receipt data · Scaled to {FAMILY_KCAL} kcal/day · USDA FoodData Central</p>
</header>
<div class="wrap">

<div class="note">
  <strong>How to read this report:</strong>
  Each Delhaize receipt item is mapped to a USDA food database entry by an LLM.
  Nutrient contributions use per-100g values multiplied by the grams extracted from
  the product name (or a default serving if no weight is listed).
  All baskets are then <strong>scaled to {FAMILY_KCAL} kcal</strong>,
  so values represent "if the family ate this basket's mix of foods to reach
  {FAMILY_KCAL} kcal/day, how much of each nutrient would they get?"
  Compared against adult DRVs. Match rate: {match_r:.1f}% of rows.
</div>

<div class="grid">
  <div class="card"><div class="lbl">Shopping trips</div><div class="val">{n_trips}</div></div>
  <div class="card"><div class="lbl">Total line items</div><div class="val">{n_items:,}</div></div>
  <div class="card"><div class="lbl">Unique foods</div><div class="val">{n_foods}</div></div>
  <div class="card"><div class="lbl">Years tracked</div><div class="val">{len(years)}</div></div>
  <div class="card"><div class="lbl">Match rate</div><div class="val">{match_r:.0f}%</div></div>
  <div class="card"><div class="lbl">Kcal reference</div><div class="val">{FAMILY_KCAL}</div><div class="sub">kcal/day</div></div>
</div>
"""]

    # ── Per-year nutrient tables ───────────────────────────────────────────────
    parts.append("<h2>📊 Yearly Nutrient Intake vs DRV (scaled to 2500 kcal/day)</h2>")
    parts.append('<p>Each value is the average across all shopping trips in that year, '
                 'normalised to a 2500 kcal basket.</p>')

    for year in years:
        row = yearly_df[yearly_df['year'] == year].iloc[0]
        n_yr_trips = len(trips_df[trips_df['year'] == year])
        parts.append(f'<h3>🗓 {year} <small style="color:#888">– {n_yr_trips} trips</small></h3>')
        parts.append('<table><tr><th>Nutrient</th><th>Per 2500 kcal basket avg</th>'
                     '<th>DRV</th><th>Unit</th><th>% of DRV</th></tr>')
        for nut in KEY_NUTRIENTS:
            if nut not in row.index:
                continue
            val     = row[nut]
            drv_val = drv.get(nut)
            unit    = units.get(nut, "")
            if drv_val and drv_val > 0 and pd.notna(val):
                pct  = val / drv_val * 100
                bar  = _bar(pct)
                pct_str = f"{pct:.0f}%"
            else:
                bar  = "—"
                pct_str = "—"
            drv_str = f"{drv_val:.0f}" if drv_val else "—"
            val_str = f"{val:.1f}" if pd.notna(val) else "—"
            parts.append(f"<tr><td>{nut}</td><td>{val_str}</td>"
                         f"<td>{drv_str}</td><td>{unit}</td><td>{bar}</td></tr>")
        parts.append("</table>")

    # ── Year-over-year evolution ───────────────────────────────────────────────
    if len(years) > 1:
        parts.append("<h2>📈 Year-over-Year Evolution</h2>")
        parts.append("<table><tr><th>Nutrient</th>")
        for y in years:
            parts.append(f"<th>{y}</th>")
        parts.append("<th>Trend</th></tr>")

        for nut in KEY_NUTRIENTS:
            if nut not in yearly_df.columns:
                continue
            parts.append(f"<tr><td>{nut} <small>({units.get(nut, '')})</small></td>")
            vals = []
            for y in years:
                subset = yearly_df[yearly_df['year'] == y]
                v = subset[nut].values[0] if len(subset) else np.nan
                vals.append(v)
                drv_val = drv.get(nut)
                if drv_val and pd.notna(v):
                    pct = v / drv_val * 100
                    color = "#28a745" if 70 <= pct <= 120 else ("#ffc107" if pct < 70 else "#dc3545")
                    parts.append(f'<td style="color:{color};font-weight:600">{v:.1f}</td>')
                else:
                    parts.append(f"<td>{'—' if pd.isna(v) else f'{v:.1f}'}</td>")

            clean = [v for v in vals if pd.notna(v)]
            if len(clean) >= 2:
                pct_change = (clean[-1] - clean[0]) / max(abs(clean[0]), 1e-9) * 100
                if pct_change > 5:
                    parts.append('<td class="evo-up">↑</td>')
                elif pct_change < -5:
                    parts.append('<td class="evo-down">↓</td>')
                else:
                    parts.append('<td class="evo-flat">→</td>')
            else:
                parts.append("<td>—</td>")
            parts.append("</tr>")
        parts.append("</table>")

    # ── Per-trip heatmap summary (collapsible) ─────────────────────────────────
    parts.append("<h2>🛒 Per-Trip Breakdown</h2>")
    parts.append('<details><summary>Show all trips (Energy, Protein, Carbs, Fat after scaling)</summary>')
    parts.append('<table><tr><th>Date</th><th>Trip</th><th>Items</th>'
                 '<th>Energy (raw kcal)</th><th>Protein (g)</th><th>Carbs (g)</th><th>Fat (g)</th></tr>')
    for _, tr in trips_df.sort_values('date').iterrows():
        raw_e = tr.get('raw_energy', '—')
        raw_e_str = f"{raw_e:.0f}" if pd.notna(raw_e) else "—"
        prot_str = f"{tr.get('Protein', np.nan):.1f}" if pd.notna(tr.get('Protein')) else "—"
        carb_str = f"{tr.get('Carbohydrate', np.nan):.1f}" if pd.notna(tr.get('Carbohydrate')) else "—"
        fat_str  = f"{tr.get('Total fat', np.nan):.1f}" if pd.notna(tr.get('Total fat')) else "—"
        parts.append(f"<tr><td>{str(tr['date'])[:10]}</td><td>{tr['source_file']}</td>"
                     f"<td>{tr['n_items']}</td><td>{raw_e_str}</td>"
                     f"<td>{prot_str}</td><td>{carb_str}</td><td>{fat_str}</td></tr>")
    parts.append("</table></details>")

    # ── Top foods ─────────────────────────────────────────────────────────────
    parts.append("<h2>🏆 Most Purchased Foods</h2>")
    matched = purchases[purchases['llm_action'] == 'match'].copy()
    matched['year'] = pd.to_datetime(matched['date']).dt.year
    for year in years:
        top = (matched[matched['year'] == year]
               .groupby('pyfooda_name').size()
               .sort_values(ascending=False).head(25))
        parts.append(f"<h3>{year}</h3><p>")
        for food, cnt in top.items():
            parts.append(f'<span class="pill">{food} ({cnt})</span>')
        parts.append("</p>")

    # ── Category breakdown ────────────────────────────────────────────────────
    if not cat_df.empty:
        parts.append("<h2>🗂 Food Category Distribution</h2>")
        for year in years:
            sub = cat_df[cat_df['year'] == year].head(15)
            if sub.empty:
                continue
            parts.append(f"<h3>{year}</h3>")
            parts.append("<table><tr><th>Category</th><th>Items</th><th>%</th><th>Bar</th></tr>")
            for _, r in sub.iterrows():
                bw = min(int(r['pct']), 100)
                parts.append(f"<tr><td>{r['category']}</td><td>{r['count']}</td>"
                              f"<td>{r['pct']:.1f}%</td>"
                              f'<td><span class="bar-bg"><span class="bar-fg ok" '
                              f'style="width:{bw}%"></span></span></td></tr>')
            parts.append("</table>")

    parts.append("</div></body></html>")
    return "\n".join(parts)


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    if not PURCHASES_CSV.exists():
        raise FileNotFoundError(f"Run 01_build_mapping.py first. Missing: {PURCHASES_CSV}")

    print("Loading pyfooda…")
    foods_df, drv, units = load_pyfooda()
    print(f"  {len(foods_df):,} foods · {len(drv)} DRV nutrients")

    print("Loading purchases…")
    purchases = pd.read_csv(PURCHASES_CSV, dtype=str)
    purchases['date']  = pd.to_datetime(purchases['date'])
    purchases['price'] = pd.to_numeric(purchases['price'], errors='coerce')
    purchases['grams_in_name'] = pd.to_numeric(purchases['grams_in_name'], errors='coerce')
    print(f"  {len(purchases):,} rows  ·  "
          f"{(purchases['llm_action'] == 'match').sum():,} matched")

    nutrient_cols = [c for c in KEY_NUTRIENTS if c in foods_df.columns]
    missing = [c for c in KEY_NUTRIENTS if c not in foods_df.columns]
    if missing:
        print(f"  (columns not in database: {missing})")

    print("Computing per-trip nutrition…")
    trips_df = compute_trip_nutrition(purchases, foods_df, nutrient_cols)
    print(f"  {len(trips_df)} trips processed")

    print("Computing yearly averages…")
    yearly_df = compute_yearly(trips_df, nutrient_cols)

    print("Computing category breakdown…")
    cat_df = category_breakdown(purchases, foods_df)

    print("Writing CSVs…")
    trips_df.to_csv(REPORT_TRIPS, index=False)
    # Yearly with DRV annotation
    rows_out = []
    for _, row in yearly_df.iterrows():
        for nut in nutrient_cols:
            v = row[nut]
            d = drv.get(nut)
            rows_out.append({
                "year": row["year"],
                "nutrient": nut,
                "unit": units.get(nut, ""),
                "value_per_2500kcal_trip": round(v, 3) if pd.notna(v) else None,
                "drv": d,
                "pct_drv": round(v / d * 100, 1) if d and pd.notna(v) else None,
            })
    pd.DataFrame(rows_out).to_csv(REPORT_YEARLY, index=False)
    print(f"  {REPORT_TRIPS}")
    print(f"  {REPORT_YEARLY}")

    print("Generating HTML report…")
    html = build_html(purchases, trips_df, yearly_df, cat_df, drv, units)
    REPORT_HTML.write_text(html, encoding="utf-8")
    print(f"  {REPORT_HTML}")

    # Quick console summary
    print("\n── Yearly snapshot (% DRV at 2500 kcal) ──")
    snap_nuts = ["Energy", "Protein", "Calcium", "Iron", "Vitamin C", "Vitamin D (D2 + D3)"]
    for year in sorted(yearly_df['year'].unique()):
        row = yearly_df[yearly_df['year'] == year].iloc[0]
        parts_str = []
        for n in snap_nuts:
            v = row.get(n, np.nan)
            d = drv.get(n)
            if d and pd.notna(v):
                parts_str.append(f"{n}: {v/d*100:.0f}%")
        print(f"  {year}: " + "  ".join(parts_str))

    print("\nDone — open nutrition_report.html to explore the full report.")


if __name__ == "__main__":
    main()
