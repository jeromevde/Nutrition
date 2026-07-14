# Pyfooda Data Quality Issues

Found while running the nutrition pipeline against the pyfooda v0.6.0 ingredient database.
All values are per 100g unless noted.

---

## 1. POTATO — aggregation includes chips / fried products

**ingredient_id:** `potato`

| Nutrient | DB value | Real value (raw potato) | Error |
|---|---|---|---|
| Energy | **352.7 kcal** | ~77 kcal | 4.6× too high |
| Iron | **6.73 mg** | ~0.6 mg | 11× too high |
| Protein | **8.11 g** | ~2.0 g | 4× too high |
| Calcium | 53.4 mg | ~12 mg | 4.5× too high |

**Root cause:** The aggregation likely pulls branded potato chips, fries, and fortified potato products alongside raw potatoes. All macro values are roughly 4–11× the expected raw-potato profile.

**Impact:** A 1 kg bag of potatoes (common purchase) contributed 67 mg of iron per trip — nearly 9× the adult daily DRV. This inflated the reported iron and energy for every trip containing potatoes.

---

## 2. FENNEL — aggregation includes fennel seeds

**ingredient_id:** `fennel`

| Nutrient | DB value | Real value (fennel bulb) | Error |
|---|---|---|---|
| Energy | **344.9 kcal** | ~31 kcal | 11× too high |
| Iron | **18.54 mg** | ~0.7 mg | 26× too high |
| Protein | **15.8 g** | ~1.2 g | 13× too high |
| Calcium | **1196 mg** | ~49 mg | 24× too high |

**Root cause:** Fennel seeds (very nutrient-dense) are being aggregated with fennel bulb. Seeds have ~37mg iron/100g; the average is being dragged far above the bulb profile.

**Impact:** A 500g fennel bulb purchase contributed 92 mg iron — 11× the adult daily DRV.

---

## 3. LARD — appears to contain Swiss chard / leafy green data

**ingredient_id:** `lard`

| Nutrient | DB value | Real value (pork lard) | Error |
|---|---|---|---|
| Energy | **34.9 kcal** | ~900 kcal | 26× too low |
| Vitamin C | **39.0 mg** | 0 mg | should be zero |
| Protein | 5.81 g | ~0 g | should be near zero |
| Calcium | 70 mg | ~0 mg | should be near zero |

**Root cause:** The nutrient profile matches Swiss chard (blette/bette in French), not pork lard. Likely a French vocabulary collision: `lard` (pork fat in French) being matched to `blette`/`bette`-tagged USDA entries.

**Impact:** Lardons (mapped to `lard`) had near-zero energy, inflating the energy scale factor for every trip containing them. Vitamin C was falsely attributed to lard purchases.

---

## 4. BEEF — calcium anomaly

**ingredient_id:** `beef`

| Nutrient | DB value | Real value (lean beef) | Error |
|---|---|---|---|
| Calcium | **159 mg** | ~12–20 mg | 8–13× too high |
| Thiamin | **1.0 mg** | ~0.06 mg | 17× too high |

**Root cause:** Aggregation likely includes beef+dairy composite dishes (lasagne, cheeseburgers, beef+cheese products) that bring in dairy calcium.

**Impact:** Inflates calcium readings for any purchase mapped to `beef`.

---

## 5. PIE CRUST — extreme B-vitamin outliers

**ingredient_id:** `pie_crust`

| Nutrient | DB value | DRV | Multiple |
|---|---|---|---|
| Vitamin B-12 | **480.8 µg** | 2.4 µg | **200× DRV per 100g** |
| Thiamin | **48.3 mg** | 1.2 mg | **40× DRV per 100g** |
| Riboflavin | **48.2 mg** | 1.3 mg | **37× DRV per 100g** |

**Root cause:** Likely a USDA data entry error for a fortified or enriched product that got aggregated into the generic `pie_crust` ingredient.

**Impact:** These are caught by the pipeline's density cap (`5× DRV/100g`) and suppressed, so they do not reach the report. But the entry is still a data issue.

---

## 6. CHICKEN — energy higher than expected

**ingredient_id:** `chicken`

| Nutrient | DB value | Lean chicken breast | Note |
|---|---|---|---|
| Energy | **454 kcal** | ~165 kcal | Aggregates fried/breaded chicken |

**Root cause:** The aggregation includes fried and processed chicken products (nuggets, fried chicken) alongside raw chicken breast. 454 kcal/100g matches fried chicken.

**Impact:** Overstates energy contribution of chicken purchases; makes scale factor smaller, which slightly deflates other nutrients.

---

## Summary

| Ingredient | Severity | Workaround applied |
|---|---|---|
| `potato` | 🔴 Critical | Mapped to `ignore` in pipeline |
| `fennel` | 🔴 Critical | Mapped to `ignore` in pipeline |
| `lard` | 🔴 Critical | Remapped to `pork` in pipeline |
| `beef` | 🟠 High | Still used (iron/protein OK; calcium/thiamin inflated) |
| `pie_crust` | 🟡 Medium | Density cap suppresses B12/thiamin/riboflavin |
| `chicken` | 🟡 Medium | Still used (protein OK; energy inflated) |

The most impactful fix would be to separate:
- `potato` (raw) from `potato_chip`, `french_fries`, `potato_product`
- `fennel` (bulb) from `fennel_seed`
- `lard` (rendered pork fat) from any vegetable vocabulary matches
