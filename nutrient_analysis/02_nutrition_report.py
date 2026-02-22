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

    def _purchases(yk: str) -> list:
        """Build a flat list of all matched purchase rows for the JS table."""
        sub = matched if yk == 'all' else matched[matched['year'] == int(yk)]
        rows_out: list[dict] = []
        for _, row in sub.iterrows():
            g = row.get('grams_in_name')
            rows_out.append({
                'date':          str(row['date'])[:10],
                'product_name':  str(row.get('product_name', '')),
                'pyfooda_name':  str(row['pyfooda_name']),
                'grams':         round(float(g), 1) if pd.notna(g) else None,
                'price':         round(float(row['price']), 2) if pd.notna(row.get('price')) else None,
            })
        return rows_out

    return {
        'years':              years,
        'key_nutrients':      KEY_NUTRIENTS,
        'family_kcal':        FAMILY_KCAL,
        'stats':              {k: _stats(k)              for k in year_keys},
        'nutrients':          {k: _nutrients(k)          for k in year_keys},
        'nutrient_top_foods': {k: _nutrient_top_foods(k) for k in year_keys},
        'top_foods':          {k: _top_foods(k)          for k in year_keys},
        'purchases':          {k: _purchases(k)          for k in year_keys},
    }



# ── HTML template ─────────────────────────────────────────────────────────────

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Nutrition __YR_STR__</title>
<style>
:root{
  --accent:#2563eb;--accent-bg:#eff6ff;
  --green:#16a34a;--yellow:#d97706;--red:#dc2626;
  --bg:#f8fafc;--surface:#fff;--border:#e2e8f0;
  --text:#1e293b;--muted:#94a3b8;--r:8px;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--text);line-height:1.5}
.wrap{max-width:1000px;margin:0 auto;padding:18px 28px 40px}
/* meta bar */
.meta{display:flex;gap:16px;flex-wrap:wrap;padding:6px 0 10px;font-size:.72rem;color:var(--muted);letter-spacing:.02em}
.meta span::after{content:'\00b7';margin-left:16px;opacity:.4}
.meta span:last-child::after{content:''}
/* pill row controls */
.ctrl-row{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px}
.pill-btn{padding:4px 14px;border-radius:16px;border:1.5px solid var(--border);
  background:transparent;cursor:pointer;font-size:.8rem;color:var(--muted);transition:all .12s}
.pill-btn.active{background:var(--accent);color:#fff;border-color:var(--accent)}
.pill-btn.sec.active{background:var(--accent-bg);color:var(--accent);border-color:var(--accent)}
/* nutrients table */
.nut-table{width:100%;border-collapse:collapse;background:var(--surface);
  border:1px solid var(--border);border-radius:var(--r);overflow:hidden}
.nut-table thead th{background:#f1f5f9;padding:8px 12px;font-size:.7rem;
  text-align:left;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;border-bottom:1px solid var(--border)}
.nut-table tbody tr{cursor:pointer;transition:background .1s}
.nut-table tbody tr:hover{background:var(--accent-bg)}
.nut-table td{padding:7px 12px;border-bottom:1px solid var(--border);font-size:.85rem}
.nut-table tbody tr:last-child td{border-bottom:none}
.nut-name{font-weight:500}
.bar-wrap{display:flex;align-items:center;gap:8px}
.bar-bg{flex:1;max-width:160px;height:7px;background:#e2e8f0;border-radius:4px;overflow:hidden}
.bar-fg{height:100%;border-radius:4px}
.bar-green{background:var(--green)}.bar-yellow{background:var(--yellow)}.bar-red{background:var(--red)}
.pct-badge{font-size:.78rem;font-weight:700;min-width:40px;text-align:right}
.pct-green{color:var(--green)}.pct-yellow{color:var(--yellow)}.pct-red{color:var(--red)}
.nut-val{color:var(--muted);font-size:.78rem}
/* purchases table */
.p-table{width:100%;border-collapse:collapse;background:var(--surface);
  border:1px solid var(--border);border-radius:var(--r);overflow:hidden;font-size:.82rem}
.p-table thead th{background:#f1f5f9;padding:7px 10px;font-size:.7rem;text-align:left;
  color:var(--muted);text-transform:uppercase;letter-spacing:.04em;border-bottom:1px solid var(--border);
  cursor:pointer;user-select:none;white-space:nowrap}
.p-table thead th:hover{color:var(--accent)}
.p-table td{padding:5px 10px;border-bottom:1px solid var(--border)}
.p-table tbody tr:last-child td{border-bottom:none}
.p-table tbody tr:hover{background:var(--accent-bg)}
.date-hdr td{background:#f8fafc;font-weight:600;font-size:.78rem;color:var(--accent);padding:8px 10px 4px}
.name-hdr td{background:#f8fafc;font-weight:600;font-size:.78rem;color:var(--accent);padding:8px 10px 4px}
.p-muted{color:var(--muted)}
.p-grams{font-weight:600;color:var(--text)}
/* modal */
#modal-bg{display:none;position:fixed;inset:0;background:rgba(0,0,0,.35);z-index:100;align-items:center;justify-content:center}
#modal-bg.open{display:flex}
#modal{background:var(--surface);border-radius:12px;max-width:500px;width:92%;max-height:80vh;overflow-y:auto;box-shadow:0 16px 48px rgba(0,0,0,.18)}
.modal-hdr{padding:16px 18px 12px;border-bottom:1px solid var(--border);display:flex;align-items:flex-start;justify-content:space-between;gap:10px;position:sticky;top:0;background:var(--surface);border-radius:12px 12px 0 0}
.modal-title{font-size:.95rem;font-weight:600}
.modal-sub{font-size:.75rem;color:var(--muted);margin-top:2px}
#modal-close{background:none;border:none;font-size:1.3rem;cursor:pointer;color:var(--muted);line-height:1;padding:2px 6px;border-radius:6px;flex-shrink:0}
#modal-close:hover{background:var(--border)}
.modal-body{padding:14px 18px 18px}
.mtable{width:100%;border-collapse:collapse;font-size:.82rem}
.mtable tr:not(:last-child) td{border-bottom:1px solid var(--border)}
.mtable td{padding:6px 5px}
.mbar-wrap{display:flex;align-items:center;gap:6px}
.mbar-bg{flex:1;height:5px;background:#e2e8f0;border-radius:3px;overflow:hidden}
.mbar-fg{height:100%;border-radius:3px;background:var(--accent)}
.mpct{font-size:.75rem;font-weight:700;color:var(--accent);min-width:34px;text-align:right}
</style></head>
<body>
<div class="wrap">
  <div class="meta" id="meta-bar"></div>
  <div class="ctrl-row" id="tab-row">
    <button class="pill-btn active" data-tab="nutrients">Nutrients</button>
    <button class="pill-btn" data-tab="purchases">Purchases</button>
  </div>
  <div class="ctrl-row" id="year-row">
    <button class="pill-btn sec active" data-year="all">All</button>
    __YEAR_BUTTONS__
  </div>
  <!-- nutrients view -->
  <section id="v-nutrients">
    <table class="nut-table">
      <thead><tr><th>Nutrient</th><th style="min-width:200px">vs DRV</th><th>Value</th></tr></thead>
      <tbody id="nut-tbody"></tbody>
    </table>
  </section>
  <!-- purchases view -->
  <section id="v-purchases" hidden>
    <div class="ctrl-row" id="group-row">
      <button class="pill-btn sec active" data-group="date">By date</button>
      <button class="pill-btn sec" data-group="name">By name</button>
    </div>
    <div id="purchases-container"></div>
  </section>
</div>
<!-- modal -->
<div id="modal-bg"><div id="modal">
  <div class="modal-hdr"><div><div class="modal-title" id="modal-title"></div><div class="modal-sub" id="modal-sub"></div></div><button id="modal-close">&#x2715;</button></div>
  <div class="modal-body" id="modal-body"></div>
</div></div>
<script>
const DATA=__DATA_JSON__;
let state={tab:'nutrients',year:'all',group:'date'};
function bc(p){return p==null?'bar-green':p>=70&&p<=120?'bar-green':p<70?'bar-yellow':'bar-red';}
function pc(p){return p==null?'pct-green':p>=70&&p<=120?'pct-green':p<70?'pct-yellow':'pct-red';}
function fmt(v,d){if(v==null)return'\u2014';d=d??1;return Number(v).toLocaleString(undefined,{maximumFractionDigits:d});}
function sh(n,mx){mx=mx||48;return n.length>mx?n.slice(0,mx-1)+'\u2026':n;}

function renderMeta(){
  const s=DATA.stats[state.year];
  document.getElementById('meta-bar').innerHTML=
    `<span>${s.trips} trips</span><span>${s.items.toLocaleString()} items</span>`+
    `<span>${s.foods} unique foods</span><span>${s.match_pct}% matched</span>`+
    `<span>${DATA.family_kcal} kcal ref</span>`;
}

function renderNutrients(){
  const nuts=DATA.nutrients[state.year];
  document.getElementById('nut-tbody').innerHTML=DATA.key_nutrients.map(n=>{
    const d=nuts[n];if(!d)return'';
    const p=d.pct,w=p==null?0:Math.min(p/150*100,100);
    return `<tr data-nut="${n}"><td class="nut-name">${n}</td>`+
      `<td><div class="bar-wrap"><div class="bar-bg"><div class="bar-fg ${bc(p)}" style="width:${w.toFixed(0)}%"></div></div>`+
      `<span class="pct-badge ${pc(p)}">${p!=null?p+'%':'\u2014'}</span></div></td>`+
      `<td class="nut-val">${fmt(d.value)} ${d.unit}</td></tr>`;
  }).join('');
  document.querySelectorAll('#nut-tbody tr[data-nut]').forEach(tr=>{
    tr.addEventListener('click',()=>openNutModal(tr.dataset.nut));
  });
}

function renderPurchases(){
  const rows=DATA.purchases[state.year]||[];
  const c=document.getElementById('purchases-container');
  if(!rows.length){c.innerHTML='<p style="color:var(--muted);padding:20px 0">No data.</p>';return;}
  if(state.group==='date'){
    // group by date
    const byDate={};
    rows.forEach(r=>{(byDate[r.date]=byDate[r.date]||[]).push(r);});
    const dates=Object.keys(byDate).sort().reverse();
    let h='<table class="p-table"><thead><tr><th>Product</th><th>Matched</th><th>Grams</th><th>Price</th></tr></thead><tbody>';
    dates.forEach(d=>{
      h+=`<tr class="date-hdr"><td colspan="4">${d} (${byDate[d].length} items)</td></tr>`;
      byDate[d].forEach(r=>{
        h+=`<tr><td>${sh(r.product_name,50)}</td><td class="p-muted">${sh(r.pyfooda_name,40)}</td>`+
          `<td class="p-grams">${r.grams!=null?fmt(r.grams,0)+' g':'\u2014'}</td>`+
          `<td class="p-muted">${r.price!=null?'\u20ac'+fmt(r.price,2):''}</td></tr>`;
      });
    });
    h+='</tbody></table>';
    c.innerHTML=h;
  } else {
    // group by name
    const byName={};
    rows.forEach(r=>{
      const k=r.pyfooda_name;
      if(!byName[k])byName[k]={name:k,orig:[],dates:[],grams:[],count:0,totalG:0};
      const e=byName[k];e.count++;e.orig.push(r.product_name);e.dates.push(r.date);
      if(r.grams!=null){e.grams.push(r.grams);e.totalG+=r.grams;}
    });
    const entries=Object.values(byName).sort((a,b)=>b.count-a.count);
    let h='<table class="p-table"><thead><tr><th>Matched name</th><th>Count</th><th>Total g</th><th>Original names</th></tr></thead><tbody>';
    entries.forEach(e=>{
      const uniqOrig=[...new Set(e.orig)].slice(0,3).map(s=>sh(s,36)).join(', ');
      const extra=new Set(e.orig).size>3?' \u2026':'';
      h+=`<tr><td style="font-weight:500">${sh(e.name,42)}</td>`+
        `<td style="font-weight:600;color:var(--accent)">${e.count}</td>`+
        `<td class="p-grams">${e.totalG>0?fmt(e.totalG,0)+' g':'\u2014'}</td>`+
        `<td class="p-muted" style="font-size:.78rem">${uniqOrig}${extra}</td></tr>`;
    });
    h+='</tbody></table>';
    c.innerHTML=h;
  }
}

function openModal(t,s,b){
  document.getElementById('modal-title').textContent=t;
  document.getElementById('modal-sub').textContent=s;
  document.getElementById('modal-body').innerHTML=b;
  document.getElementById('modal-bg').classList.add('open');
}
function closeModal(){document.getElementById('modal-bg').classList.remove('open');}

function openNutModal(nut){
  const d=DATA.nutrients[state.year][nut];if(!d)return;
  const top=(DATA.nutrient_top_foods[state.year]||{})[nut]||[];
  const sub=`avg ${fmt(d.value)} ${d.unit} \u00b7 ${d.pct!=null?d.pct+'% of DRV':'no DRV'}`+(d.drv?` (DRV ${fmt(d.drv,0)} ${d.unit})`:'');
  let body;
  if(!top.length){body='<p style="color:var(--muted);font-size:.82rem">No data.</p>';}
  else{
    const mx=top[0].amount;
    body='<table class="mtable"><tbody>'+top.map(f=>{
      const w=(f.amount/mx*100).toFixed(0);
      return `<tr><td style="font-weight:500">${sh(f.food,40)}</td>`+
        `<td><div class="mbar-wrap"><div class="mbar-bg"><div class="mbar-fg" style="width:${w}%"></div></div>`+
        `<span class="mpct">${f.pct_of_total}%</span></div></td>`+
        `<td style="text-align:right;color:var(--muted);font-size:.78rem">${fmt(f.amount)} ${d.unit}</td></tr>`;
    }).join('')+'</tbody></table>';
  }
  openModal('Top sources: '+nut,(state.year==='all'?'all years':state.year)+' \u00b7 up to 10 foods',body);
}

function render(){
  renderMeta();
  const isNut=state.tab==='nutrients';
  document.getElementById('v-nutrients')[isNut?'removeAttribute':'setAttribute']('hidden','');
  document.getElementById('v-purchases')[isNut?'setAttribute':'removeAttribute']('hidden','');
  isNut?renderNutrients():renderPurchases();
}

// wire tabs
document.querySelectorAll('#tab-row .pill-btn').forEach(b=>b.addEventListener('click',()=>{
  document.querySelectorAll('#tab-row .pill-btn').forEach(x=>x.classList.remove('active'));
  b.classList.add('active');state.tab=b.dataset.tab;render();
}));
// wire years
document.querySelectorAll('#year-row .pill-btn').forEach(b=>b.addEventListener('click',()=>{
  document.querySelectorAll('#year-row .pill-btn').forEach(x=>x.classList.remove('active'));
  b.classList.add('active');state.year=b.dataset.year;render();
}));
// wire group toggle
document.querySelectorAll('#group-row .pill-btn').forEach(b=>b.addEventListener('click',()=>{
  document.querySelectorAll('#group-row .pill-btn').forEach(x=>x.classList.remove('active'));
  b.classList.add('active');state.group=b.dataset.group;renderPurchases();
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
