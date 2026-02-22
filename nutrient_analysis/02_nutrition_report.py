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


# ── Per-food nutrient contributions ──────────────────────────────────────────

def compute_food_contributions(
    purchases: pd.DataFrame,
    foods_df: pd.DataFrame,
    nutrient_cols: list[str],
) -> pd.DataFrame:
    """
    For every matched purchase row compute raw nutrient grams contributed.
    Returns a DataFrame with cols: year, pyfooda_name, category, count, <nutrients...>
    """
    matched = purchases[purchases['llm_action'] == 'match'].copy()
    matched['grams_in_name'] = pd.to_numeric(matched['grams_in_name'], errors='coerce')
    matched['year'] = matched['date'].dt.year

    cat_col = next(
        (c for c in ('category', 'food_category') if c in foods_df.columns), None
    )

    rows: list[dict] = []
    for _, row in matched.iterrows():
        contrib = nutrient_contribution(
            row['pyfooda_name'],
            row['grams_in_name'] if pd.notna(row['grams_in_name']) else None,
            foods_df,
            nutrient_cols,
        )
        cat = 'Other'
        if cat_col and row['pyfooda_name'] in foods_df.index:
            cv = foods_df.loc[row['pyfooda_name'], cat_col]
            if pd.notna(cv):
                cat = str(cv)
        r: dict = {
            'pyfooda_name': row['pyfooda_name'],
            'year':         row['year'],
            'category':     cat,
        }
        r.update(contrib)
        rows.append(r)

    if not rows:
        return pd.DataFrame()

    df       = pd.DataFrame(rows)
    nut_here = [c for c in nutrient_cols if c in df.columns]
    count_s  = df.groupby(['year', 'pyfooda_name']).size().rename('count')
    cat_s    = df.groupby(['year', 'pyfooda_name'])['category'].first()
    sums     = df.groupby(['year', 'pyfooda_name'])[nut_here].sum()
    return sums.join(cat_s).join(count_s).reset_index()


# ── Assemble report data dict ─────────────────────────────────────────────────

def build_report_data(
    purchases: pd.DataFrame,
    trips_df: pd.DataFrame,
    yearly_df: pd.DataFrame,
    foods_df: pd.DataFrame,
    drv: dict[str, float],
    units: dict[str, str],
    nutrient_cols: list[str],
    food_contribs: pd.DataFrame,
) -> dict:
    years     = sorted(int(y) for y in yearly_df['year'].unique())
    matched   = purchases[purchases['llm_action'] == 'match'].copy()
    matched['year'] = matched['date'].dt.year
    year_keys = ['all'] + [str(y) for y in years]

    def _stats(yk: str) -> dict:
        if yk == 'all':
            yr_p, yr_m, yr_t = purchases, matched, trips_df
        else:
            y    = int(yk)
            yr_p = purchases[purchases['date'].dt.year == y]
            yr_m = matched[matched['year'] == y]
            yr_t = trips_df[trips_df['year'] == y]
        return {
            'trips':     int(len(yr_t)),
            'items':     int(len(yr_p)),
            'foods':     int(yr_m['pyfooda_name'].nunique()),
            'match_pct': round(len(yr_m) / max(len(yr_p), 1) * 100, 1),
        }

    def _nutrients(yk: str) -> dict:
        yr_t = trips_df if yk == 'all' else trips_df[trips_df['year'] == int(yk)]
        out: dict = {}
        for nut in KEY_NUTRIENTS:
            if nut not in yr_t.columns or yr_t.empty:
                continue
            val     = float(yr_t[nut].mean())
            drv_val = drv.get(nut)
            out[nut] = {
                'value': round(val, 2) if pd.notna(val) else None,
                'drv':   drv_val,
                'unit':  units.get(nut, ''),
                'pct':   round(val / drv_val * 100, 1) if drv_val and pd.notna(val) else None,
            }
        return out

    def _nutrient_top_foods(yk: str) -> dict:
        if food_contribs.empty:
            return {}
        fc = food_contribs if yk == 'all' else food_contribs[food_contribs['year'] == int(yk)]
        if fc.empty:
            return {}
        nut_here  = [c for c in KEY_NUTRIENTS if c in fc.columns]
        by_food   = fc.groupby('pyfooda_name')[nut_here].sum()
        out: dict = {}
        for nut in KEY_NUTRIENTS:
            if nut not in by_food.columns:
                continue
            col   = by_food[nut].sort_values(ascending=False)
            total = col.sum()
            out[nut] = [
                {
                    'food':         str(food),
                    'amount':       round(float(amt), 2),
                    'pct_of_total': round(float(amt) / max(float(total), 1e-9) * 100, 1),
                }
                for food, amt in col.head(10).items()
                if pd.notna(amt) and amt > 0
            ]
        return out

    def _top_foods(yk: str) -> list:
        if food_contribs.empty:
            return []
        fc = food_contribs if yk == 'all' else food_contribs[food_contribs['year'] == int(yk)]
        if fc.empty:
            return []
        agg = (
            fc.groupby('pyfooda_name')
            .agg(count=('count', 'sum'), category=('category', 'first'))
            .sort_values('count', ascending=False)
            .head(40)
        )
        entries = []
        for food, row in agg.iterrows():
            food_nuts: dict = {}
            if food in foods_df.index:
                fr = foods_df.loc[food]
                for nut in KEY_NUTRIENTS:
                    if nut in fr.index and pd.notna(fr[nut]):
                        drv_val = drv.get(nut)
                        food_nuts[nut] = {
                            'value': round(float(fr[nut]), 2),
                            'unit':  units.get(nut, ''),
                            'drv':   drv_val,
                            'pct':   round(float(fr[nut]) / drv_val * 100, 1) if drv_val else None,
                        }
            entries.append({
                'food':      str(food),
                'count':     int(row['count']),
                'category':  str(row['category']),
                'nutrients': food_nuts,
            })
        return entries

    return {
        'years':              years,
        'key_nutrients':      KEY_NUTRIENTS,
        'family_kcal':        FAMILY_KCAL,
        'stats':              {k: _stats(k)              for k in year_keys},
        'nutrients':          {k: _nutrients(k)          for k in year_keys},
        'nutrient_top_foods': {k: _nutrient_top_foods(k) for k in year_keys},
        'top_foods':          {k: _top_foods(k)          for k in year_keys},
    }



# ── HTML template (plain string — no f-string brace escaping needed) ──────────

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Family Nutrition __YR_STR__</title>
<style>
:root {
  --accent:#2563eb; --accent-h:#1d4ed8; --accent-bg:#eff6ff;
  --green:#16a34a; --yellow:#d97706; --red:#dc2626;
  --bg:#f8fafc; --surface:#fff; --border:#e2e8f0;
  --text:#1e293b; --muted:#64748b; --r:10px;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;
  background:var(--bg);color:var(--text);line-height:1.5}
header{background:var(--accent);color:#fff;padding:20px 32px}
header h1{font-size:1.4rem;font-weight:600}
header p{opacity:.8;font-size:.875rem;margin-top:2px}
.controls{display:flex;align-items:center;gap:10px;flex-wrap:wrap;
  padding:12px 32px;background:var(--surface);border-bottom:1px solid var(--border);
  position:sticky;top:0;z-index:10;box-shadow:0 1px 4px rgba(0,0,0,.06)}
.tab-btn{padding:6px 18px;border-radius:20px;border:1.5px solid var(--border);
  background:transparent;cursor:pointer;font-size:.875rem;color:var(--muted);transition:all .15s}
.tab-btn.active{background:var(--accent);color:#fff;border-color:var(--accent)}
.sep{flex:1}
.year-btn{padding:5px 14px;border-radius:20px;border:1.5px solid var(--border);
  background:transparent;cursor:pointer;font-size:.8rem;color:var(--muted);transition:all .15s}
.year-btn.active{background:var(--accent-bg);color:var(--accent);border-color:var(--accent)}
.wrap{max-width:960px;margin:0 auto;padding:24px 32px}
.stats{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:12px;margin-bottom:28px}
.stat{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:14px 16px}
.stat-lbl{font-size:.7rem;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.stat-val{font-size:1.6rem;font-weight:700;color:var(--accent);line-height:1.2}
.nut-table{width:100%;border-collapse:collapse;background:var(--surface);
  border:1px solid var(--border);border-radius:var(--r);overflow:hidden}
.nut-table thead th{background:#f1f5f9;padding:10px 14px;font-size:.75rem;
  text-align:left;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;
  border-bottom:1px solid var(--border)}
.nut-table tbody tr{cursor:pointer;transition:background .12s}
.nut-table tbody tr:hover{background:var(--accent-bg)}
.nut-table tbody td{padding:9px 14px;border-bottom:1px solid var(--border);font-size:.88rem}
.nut-table tbody tr:last-child td{border-bottom:none}
.nut-name{font-weight:500}
.bar-wrap{display:flex;align-items:center;gap:8px}
.bar-bg{flex:1;max-width:180px;height:8px;background:#e2e8f0;border-radius:4px;overflow:hidden}
.bar-fg{height:100%;border-radius:4px}
.bar-green{background:var(--green)} .bar-yellow{background:var(--yellow)} .bar-red{background:var(--red)}
.pct-badge{font-size:.8rem;font-weight:700;min-width:44px;text-align:right}
.pct-green{color:var(--green)} .pct-yellow{color:var(--yellow)} .pct-red{color:var(--red)}
.nut-val{color:var(--muted);font-size:.82rem;min-width:90px}
.note{background:#fefce8;border-left:3px solid var(--yellow);
  padding:10px 16px;border-radius:0 var(--r) var(--r) 0;
  font-size:.82rem;color:#713f12;margin-bottom:20px}
.food-list{display:flex;flex-direction:column;gap:6px}
.food-item{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);
  padding:12px 16px;cursor:pointer;transition:all .15s;
  display:grid;grid-template-columns:32px 1fr auto auto;align-items:center;gap:12px}
.food-item:hover{border-color:var(--accent);background:var(--accent-bg)}
.food-rank{font-size:.75rem;font-weight:700;color:var(--muted);text-align:center}
.food-name{font-weight:500;font-size:.9rem}
.food-cat{font-size:.72rem;color:var(--muted);margin-top:1px}
.food-count{font-size:.82rem;font-weight:700;color:var(--accent);
  background:var(--accent-bg);padding:3px 10px;border-radius:12px;white-space:nowrap}
#modal-bg{display:none;position:fixed;inset:0;background:rgba(0,0,0,.4);
  z-index:100;align-items:center;justify-content:center}
#modal-bg.open{display:flex}
#modal{background:var(--surface);border-radius:14px;max-width:520px;width:90%;
  max-height:82vh;overflow-y:auto;box-shadow:0 20px 60px rgba(0,0,0,.2)}
.modal-hdr{padding:18px 20px 14px;border-bottom:1px solid var(--border);
  display:flex;align-items:flex-start;justify-content:space-between;gap:12px;
  position:sticky;top:0;background:var(--surface);border-radius:14px 14px 0 0}
.modal-title{font-size:1rem;font-weight:600}
.modal-sub{font-size:.78rem;color:var(--muted);margin-top:3px}
#modal-close{background:none;border:none;font-size:1.4rem;cursor:pointer;
  color:var(--muted);line-height:1;padding:2px 8px;border-radius:6px;flex-shrink:0}
#modal-close:hover{background:var(--border)}
.modal-body{padding:16px 20px 20px}
.mtable{width:100%;border-collapse:collapse;font-size:.85rem}
.mtable tr:not(:last-child) td{border-bottom:1px solid var(--border)}
.mtable td{padding:7px 6px}
.mbar-wrap{display:flex;align-items:center;gap:6px}
.mbar-bg{flex:1;height:6px;background:#e2e8f0;border-radius:3px;overflow:hidden}
.mbar-fg{height:100%;border-radius:3px;background:var(--accent)}
.mpct{font-size:.78rem;font-weight:700;color:var(--accent);min-width:36px;text-align:right}
</style></head>
<body>
<header>
  <h1>&#127805; Family Nutrition</h1>
  <p>Delhaize receipt data &middot; USDA FoodData Central &middot; scaled to __FAMILY_KCAL__ kcal/day</p>
</header>
<div class="controls">
  <button class="tab-btn active" data-tab="nutrients">Nutrients</button>
  <button class="tab-btn" data-tab="foods">Most Bought</button>
  <span class="sep"></span>
  <button class="year-btn active" data-year="all">All</button>
  __YEAR_BUTTONS__
</div>
<div class="wrap">
  <div class="stats" id="stats-row"></div>
  <section id="v-nutrients">
    <div class="note">
      Each basket is scaled to <strong>__FAMILY_KCAL__ kcal/day</strong>.
      Values are trip averages for the selected period, compared with adult Dietary Reference Values.
      <strong>Click any row</strong> to see which foods contributed most to that nutrient.
    </div>
    <table class="nut-table">
      <thead><tr>
        <th>Nutrient</th>
        <th style="min-width:240px">Progress vs DRV</th>
        <th>Average value</th>
      </tr></thead>
      <tbody id="nut-tbody"></tbody>
    </table>
  </section>
  <section id="v-foods" hidden>
    <div class="note">
      Top foods by number of purchases in the selected period.
      <strong>Click any row</strong> to see its nutrient profile (per 100 g, USDA values).
    </div>
    <div class="food-list" id="food-list"></div>
  </section>
</div>
<div id="modal-bg">
  <div id="modal">
    <div class="modal-hdr">
      <div>
        <div class="modal-title" id="modal-title"></div>
        <div class="modal-sub"   id="modal-sub"></div>
      </div>
      <button id="modal-close">&#x2715;</button>
    </div>
    <div class="modal-body" id="modal-body"></div>
  </div>
</div>
<script>
const DATA = __DATA_JSON__;
let state = {tab:'nutrients', year:'all'};
function barCls(p){return p===null?'bar-green':p>=70&&p<=120?'bar-green':p<70?'bar-yellow':'bar-red';}
function pctCls(p){return p===null?'pct-green':p>=70&&p<=120?'pct-green':p<70?'pct-yellow':'pct-red';}
function fmt(v,d=1){if(v===null||v===undefined)return'\u2014';return Number(v).toLocaleString(undefined,{maximumFractionDigits:d});}
function short(n,mx=52){return n.length>mx?n.slice(0,mx-1)+'\u2026':n;}
function renderStats(){
  const s=DATA.stats[state.year];
  document.getElementById('stats-row').innerHTML=
    `<div class="stat"><div class="stat-lbl">Trips</div><div class="stat-val">${s.trips}</div></div>`+
    `<div class="stat"><div class="stat-lbl">Line items</div><div class="stat-val">${s.items.toLocaleString()}</div></div>`+
    `<div class="stat"><div class="stat-lbl">Unique foods</div><div class="stat-val">${s.foods}</div></div>`+
    `<div class="stat"><div class="stat-lbl">Match rate</div><div class="stat-val">${s.match_pct}%</div></div>`;
}
function renderNutrients(){
  const nuts=DATA.nutrients[state.year];
  document.getElementById('nut-tbody').innerHTML=DATA.key_nutrients.map(n=>{
    const d=nuts[n];if(!d)return'';
    const pct=d.pct,w=pct===null?0:Math.min(pct/150*100,100);
    return `<tr data-nutrient="${n}">`+
      `<td class="nut-name">${n}</td>`+
      `<td><div class="bar-wrap"><div class="bar-bg"><div class="bar-fg ${barCls(pct)}" style="width:${w.toFixed(0)}%"></div></div>`+
      `<span class="pct-badge ${pctCls(pct)}">${pct!==null?pct+'%':'\u2014'}</span></div></td>`+
      `<td class="nut-val">${fmt(d.value)} ${d.unit}</td></tr>`;
  }).join('');
  document.getElementById('nut-tbody').querySelectorAll('tr').forEach(tr=>{
    tr.addEventListener('click',()=>openNutrientModal(tr.dataset.nutrient));
  });
}
function renderFoods(){
  const foods=DATA.top_foods[state.year]||[];
  document.getElementById('food-list').innerHTML=foods.map((f,i)=>
    `<div class="food-item" data-food="${encodeURIComponent(f.food)}">`+
    `<div class="food-rank">#${i+1}</div>`+
    `<div><div class="food-name">${short(f.food)}</div><div class="food-cat">${f.category}</div></div>`+
    `<div class="food-count">&times;${f.count}</div>`+
    `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="2.5"><polyline points="9 18 15 12 9 6"/></svg>`+
    `</div>`
  ).join('');
  document.getElementById('food-list').querySelectorAll('.food-item').forEach(el=>{
    el.addEventListener('click',()=>openFoodModal(decodeURIComponent(el.dataset.food)));
  });
}
function openModal(title,sub,body){
  document.getElementById('modal-title').textContent=title;
  document.getElementById('modal-sub').textContent=sub;
  document.getElementById('modal-body').innerHTML=body;
  document.getElementById('modal-bg').classList.add('open');
}
function closeModal(){document.getElementById('modal-bg').classList.remove('open');}
function openNutrientModal(nut){
  const d=DATA.nutrients[state.year][nut];if(!d)return;
  const top=(DATA.nutrient_top_foods[state.year]||{})[nut]||[];
  const sub=`avg ${fmt(d.value)} ${d.unit} \u00b7 ${d.pct!==null?d.pct+'% of DRV':'no DRV'}`
           +(d.drv?` (DRV\u00a0${fmt(d.drv,0)}\u00a0${d.unit})`:'');
  let body;
  if(!top.length){
    body='<p style="color:var(--muted);font-size:.85rem;padding:4px 0">No contribution data available.</p>';
  } else {
    const mx=top[0].amount;
    body='<table class="mtable"><tbody>'+top.map(f=>{
      const w=(f.amount/mx*100).toFixed(0);
      return `<tr><td style="font-weight:500">${short(f.food,44)}</td>`+
        `<td><div class="mbar-wrap"><div class="mbar-bg"><div class="mbar-fg" style="width:${w}%"></div></div>`+
        `<span class="mpct">${f.pct_of_total}%</span></div></td>`+
        `<td style="text-align:right;color:var(--muted);font-size:.8rem">${fmt(f.amount)} ${d.unit}</td></tr>`;
    }).join('')+'</tbody></table>';
  }
  const yl=state.year==='all'?'all years':state.year;
  openModal(`Top sources of ${nut}`,`In ${yl} \u00b7 up to 10 foods by total contribution`,body);
}
function openFoodModal(food){
  const entry=(DATA.top_foods[state.year]||[]).find(f=>f.food===food);if(!entry)return;
  const yl=state.year==='all'?'all years':state.year;
  const sub=`${entry.count} purchases in ${yl} \u00b7 ${entry.category} \u00b7 values per 100 g`;
  const keys=DATA.key_nutrients.filter(n=>entry.nutrients[n]);
  let body;
  if(!keys.length){
    body='<p style="color:var(--muted);font-size:.85rem;padding:4px 0">No nutrient data in USDA database for this item.</p>';
  } else {
    body='<table class="mtable"><tbody>'+keys.map(n=>{
      const nd=entry.nutrients[n];
      return `<tr><td>${n}</td><td style="text-align:right;font-weight:600">${fmt(nd.value)}</td>`+
        `<td style="color:var(--muted);font-size:.8rem">${nd.unit}</td></tr>`;
    }).join('')+'</tbody></table>';
  }
  openModal(short(food,46),sub,body);
}
function render(){
  renderStats();
  const sn=state.tab==='nutrients';
  document.getElementById('v-nutrients')[sn?'removeAttribute':'setAttribute']('hidden','');
  document.getElementById('v-foods')[sn?'setAttribute':'removeAttribute']('hidden','');
  sn?renderNutrients():renderFoods();
}
document.querySelectorAll('.tab-btn').forEach(b=>b.addEventListener('click',()=>{
  document.querySelectorAll('.tab-btn').forEach(x=>x.classList.remove('active'));
  b.classList.add('active');state.tab=b.dataset.tab;render();
}));
document.querySelectorAll('.year-btn').forEach(b=>b.addEventListener('click',()=>{
  document.querySelectorAll('.year-btn').forEach(x=>x.classList.remove('active'));
  b.classList.add('active');state.year=b.dataset.year;render();
}));
document.getElementById('modal-close').addEventListener('click',closeModal);
document.getElementById('modal-bg').addEventListener('click',e=>{if(e.target.id==='modal-bg')closeModal();});
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeModal();});
render();
</script>
</body>
</html>"""


# ── Build HTML from data dict ─────────────────────────────────────────────────

def build_html(data: dict) -> str:
    import json as _json
    yr_str  = (
        f"{data['years'][0]}\u2013{data['years'][-1]}"
        if len(data['years']) > 1
        else str(data['years'][0])
    )
    yr_btns = ''.join(
        f'<button class="year-btn" data-year="{y}">{y}</button>'
        for y in data['years']
    )
    return (
        HTML_TEMPLATE
        .replace('__DATA_JSON__',    _json.dumps(data, ensure_ascii=False))
        .replace('__YR_STR__',       yr_str)
        .replace('__YEAR_BUTTONS__', yr_btns)
        .replace('__FAMILY_KCAL__',  str(data['family_kcal']))
    )
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

    print("Computing food nutrient contributions…")
    food_contribs = compute_food_contributions(purchases, foods_df, nutrient_cols)

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
    report_data = build_report_data(
        purchases, trips_df, yearly_df, foods_df, drv, units, nutrient_cols, food_contribs
    )
    html = build_html(report_data)
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
