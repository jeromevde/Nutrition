# Pyfooda Improvements

This note captures pyfooda/data-quality issues found while generating the Nutrition report on 2026-07-08. The local report is now coverage-aware, but these issues should be fixed upstream or handled by pyfooda-level APIs so downstream projects do not have to rediscover them.

## Why this matters

The nutrition report can only be trusted when a nutrient is present for most of the foods contributing energy. In the current report, many nutrients look low mostly because pyfooda has sparse nutrient coverage for matched foods.

Current all-years coverage by known item energy:

| Nutrient | Coverage | Reported value | Reported % DRV | Rows with nutrient |
|---|---:|---:|---:|---:|
| Sugars, Total | 1.4% | 1.57 g | 3.1% | 52 / 1657 |
| Magnesium | 23.9% | 92.89 mg | 22.1% | 581 / 1657 |
| Potassium | 43.7% | 1964.08 mg | 57.8% | 993 / 1657 |
| Zinc | 24.9% | 3.53 mg | 32.1% | 598 / 1657 |
| Vitamin A, RAE | 17.3% | 660.07 ug | 73.3% | 439 / 1657 |
| Vitamin D (D2 + D3) | 20.6% | 0.57 ug | 2.9% | 476 / 1657 |
| Vitamin B-12 | 16.2% | 0.75 ug | 31.1% | 429 / 1657 |
| Folate, total | 18.3% | 157.09 ug | 39.3% | 490 / 1657 |
| Thiamin | 19.2% | 0.32 mg | 27.0% | 500 / 1657 |
| Riboflavin | 19.2% | 0.44 mg | 33.8% | 487 / 1657 |

Interpretation: these low values should be treated as incomplete data, not reliable intake estimates.

## Specific data issues observed

### Foods with partial nutrient payloads but missing Energy

These rows contribute some nutrients but no Energy, which breaks calorie-weighted reporting and can silently distort scaling.

| Pyfooda food | Receipt examples | Current issue |
|---|---|---|
| Squash, zucchini, raw | COURGETTES | Has Vitamin C/Folate but no Energy/macros in selected row. |
| Oil, canola | 500ML BECEL HUILE | Has saturated fat but no Energy/Total fat. This undercounts oils badly. |
| HEINZ TOMATO KETCHUP | HEINZ TOM KET / KETCH | Has sodium and other nutrients but no Energy. |
| celery, raw | CELERI VERT | Partial minerals/macros, no Energy. |
| COTE D'OR NOIR DE NOIR CHOCOLATE TABLET DARK | NOIR DE NOIR C OR | Partial nutrients, no Energy. |
| Hummus | HUMMUS | Partial minerals/fat, no Energy. |
| MILKA CHOCOLATE | MILKA CHOCO | Partial nutrients, no Energy. |
| OREO COOKIES 154 GR | OREO GRIG VANILLE | Partial nutrients, no Energy. |
| brazil nuts, raw | D4L SG BRAZIL | Partial minerals/fat, no Energy. |

Desired pyfooda behavior: either return a complete preferred row for these food names, or expose completeness metadata so callers can choose a better duplicate/fallback row.

### Duplicate or alternate entries with very different nutrient profiles

| Food family | Problem |
|---|---|
| Carpaccio/truffle carpaccio | `TRUFFLE CARPACCIO` is 600 kcal and 65 g fat / 100 g, while `SUMMER TRUFFLE CARPACCIO` is 91 kcal and 8.42 g fat / 100 g. Downstream matchers need a way to detect/avoid extreme branded outliers. |
| Cream | `Cream, fluid, heavy whipping` is complete but too rich for many European receipt labels like `CREME 20 CL`. Pyfooda should expose common cream-fat variants clearly, with canonical names or better aliases. |
| Potato | `Potatoes, raw, skin` is easily selected for `PDT GRENAILLE`, but this means potato skin, not whole potatoes with skin. Alias guidance or canonical preference should avoid this. |
| Cherry tomatoes | `CHERRY TOMATOES, CHERRY` has high iron for raw tomatoes and may be a branded/odd row. A canonical raw tomato row should be preferred for generic cherry tomato labels. |

### Branded rows often lack core nutrients

Many branded rows have only a subset of nutrients. This is especially harmful when a row has enough data to look valid but misses sugars, magnesium, B vitamins, vitamin D, or Energy.

Examples from the current report:

- BEURRE D'ISIGNY: has Energy/Total fat but misses many micronutrients and saturated fat/cholesterol compared with generic butter rows.
- MOZZARELLA: plausible macros but sparse micronutrients.
- HAZELNUT SPREAD / chocolates / cakes: often missing sugars and micronutrients.
- JAMBON DE PARIS HAM: plausible sodium/protein but sparse B vitamins.
- TORTELLONI and pasta rows: often missing sugars/micronutrients.

Desired pyfooda behavior: prefer complete generic/FDC reference rows for generic names, and rank branded rows lower when nutrient completeness is poor.

## Proposed pyfooda improvements

1. Add nutrient completeness metadata

Expose per-food fields such as:

- `nutrient_count`
- `has_energy`
- `macro_coverage_complete`
- `key_micronutrient_coverage_pct`
- `missing_key_nutrients`

This lets downstream tools avoid silent zero assumptions.

2. Improve duplicate selection

When multiple rows share or closely match a food name, prefer rows by:

1. exact foodName match with Energy present;
2. complete macro coverage;
3. complete common micronutrients;
4. reference/foundation/sr_legacy over sparse branded rows;
5. branded row only when the query is clearly branded and the row is complete enough.

3. Provide canonical aliases for common grocery concepts

Examples:

- courgette -> zucchini, raw with complete energy/macros;
- Delhaize/European `creme 20 cl` / cooking cream -> cream 20% fat variant;
- grenailles / potatoes -> whole potato with flesh+skin, not potato skin only;
- tomato cerise -> raw cherry/grape tomato canonical row;
- cooking oils -> oil rows with Energy=884 kcal and Total fat=100 g.

4. Flag extreme density outliers

Pyfooda should expose warnings for rows with unusual densities, for example:

- >60 g total fat / 100 g outside oils/butter/nuts;
- >25 g saturated fat / 100 g outside butter/oils;
- micronutrient >1x DRV / 100 g for ordinary foods;
- Energy missing while any macro/micronutrient exists.

This does not mean the row is wrong, but downstream matchers should review it before using it as a generic match.

5. Add local/composable override support

Pyfooda or downstream helpers should allow a small override table keyed by foodName, brand, or canonical category. Useful fields:

- replacement foodName;
- corrected per-100g nutrient values;
- confidence/source note;
- reason: `missing_energy`, `sparse_branded_row`, `wrong_density`, `generic_alias`.

This would let projects patch known issues without forking pyfooda data.

## Priority fixes for this repo

If improving pyfooda itself, start here:

1. Fix or replace `Oil, canola` so it has Energy and Total fat.
2. Ensure `Squash, zucchini, raw` has complete Energy/macros.
3. Prefer a sane tomato/cherry tomato canonical row for generic tomato matches.
4. Add a whole-potato canonical row/alias distinct from `Potatoes, raw, skin`.
5. Add cream-fat variants and aliases for European `creme` receipt labels.
6. Add completeness ranking so sparse branded chocolate/cake/butter rows do not suppress sugars and micronutrients.
7. Add API support for reporting nutrient coverage so downstream reports can mark low-confidence nutrients automatically.

## Current local mitigation

The Nutrition report now includes `coverage_pct` per nutrient and visually marks nutrients below 70% coverage as low coverage. This prevents pyfooda missingness from being interpreted as reliable low intake, but it does not fix the upstream data gaps.
