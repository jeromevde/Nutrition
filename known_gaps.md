# Known Data Quality Gaps & Analysis Notes

_Last updated: 2026-05-13_

---

## 1. Low DRV values that are REAL dietary gaps

### Magnesium (13–33% DRV)
- Only **1 nut/seed purchase** and **4 legume purchases** in 2.5 years of data
- Nuts, seeds, and legumes are the primary dietary magnesium sources
- Dark leafy greens (spinach → `EPINARD`) are currently all **unmatched/ignored**
- Top contributor is actually `Pork, ground, raw` (19mg/100g) — shows how sparse the real sources are

### Vitamin D (3–8% DRV)
- Expected for Belgium (low sun, no fortified foods)
- No fatty fish purchased in meaningful volume; no fortified dairy matched

### Vitamin C (48–49% DRV)
- Likely real — kiwi, strawberries, clementines carry most of it but aren't bought every week
- `CITRON TEA` branded entry has 225mg/100g which is plausible for a tea concentrate

### Vitamin B-12 (12–51% DRV)
- Only 9 matched foods have B12 > 1µg/100g across all purchases
- Several high-B12 unmatched items: `NOISETTES D AGNEAU` (lamb), `BRUNIR/SERVIR VEAU` (veal prep), `KIPFILET BLOND XL` (chicken)
- Hard cheese, beef steaks are either unmatched or matched to branded entries lacking B12 data

### Folate (21–40% DRV)
- Avocado carries ~25% of total folate alone
- Leafy greens (spinach, broccoli) largely unmatched
- **IMPORTANT**: USDA pasta entries reflect **US law-mandated enrichment** (214µg/100g folate). Belgian pasta is NOT enriched → pasta folate contribution is likely **2–4× overstated**

---

## 2. Numbers that are DATA QUALITY ARTIFACTS

### Zinc swings wildly (128% in 2023 → 20% in 2024)
- `GREEN BEANS` is a **branded_food** entry with `Zinc = 4.38 mg/100g` — **12× the real value**
- Foundation food `Beans, snap, green, raw` = 0.35mg/100g
- The density cap (5× DRV/100g) doesn't catch this: 4.38/11 = 0.4× — below threshold
- Year swing = green beans were bought in 2023 but not 2024
- **Root cause**: FAISS prefers branded entries by name match, not nutritional quality

### Sodium still inflated despite salt density cap
- `Salt, table` (38,758mg Na/100g, 14 purchases) is correctly suppressed
- But `CHERRY TOMATO BRUSCHETTA` (1500mg Na/100g, branded) and `TOM TOM SAUCE` (1133mg Na/100g) dominate
- These may be real values for condiment sauces — but unclear if the 100g reference is accurate for actual use

### Folate overstated via enriched US pasta
- All pasta entries (`PENNE RIGATE`, `CASARECCE`, `BARILLA SPAGHETTI`) show 214µg folate/100g
- This is US-enriched value; actual Belgian pasta = ~20µg/100g
- Effectively ~10× overstatement on folate from pasta

### Potassium `Lays Garlic 1.5z`
- 1200mg K/100g from a branded entry — plausible for potato chips but needs validation

---

## 3. Unmatched items that would improve coverage

### Meat/protein (currently ignored):
- `NOISETTES D AGNEAU` (9 purchases) — lamb cutlets → B12, Zinc, Protein
- `BRUNIR/SERVIR VEAU` (2 purchases) — veal
- `ROSETTE PURE PORC` (2 purchases) — pork sausage
- `KIPFILET BLOND XL` (1 purchase) — chicken fillet

### Dairy (currently ignored):
- `CARLSB CREME ENT A` (9 purchases) — likely crème entière (full cream)
- `YAOURT MIGRE BIO` (1 purchase) — bio low-fat yogurt
- `KROK FLOCONS LAIT` (1 purchase)

---

## 4. Systemic issue: branded vs canonical USDA entries

Almost all suspicious nutrient values come from **branded_food** entries being selected over canonical **foundation_food / sr_legacy** entries. The FAISS index ranks by semantic name similarity, so a branded product named "GREEN BEANS" outranks "Beans, snap, green, raw" even though the latter has correct nutritional data.

**Proposed fix**: In `resolve_match()`, prefer foundation_food/sr_legacy candidates over branded_food when both semantically match. This would fix GREEN BEANS zinc, and likely several other outliers.

---

## 5. Grams coverage
- After `--remap-nullgrams` run: **0/1744** matched rows use 100g default (100% have explicit grams)
- Before fix: 390/613 matched entries had null grams (63%)

---

## 6. Density cap suppressed pairs (in our data)
| Food | Nutrient | Per 100g | DRV | Ratio |
|------|----------|----------|-----|-------|
| Salt, table | Sodium | 38,758mg | 1,500mg | 26× |
| 100% Organic Parsley | Cholesterol | 13,000mg | 300mg | 43× ← USDA data error |
| 100% Organic Parsley | Sat. fat | 400mg | 20mg | 20× ← USDA data error |
| 100% Organic Parsley | Iron | 72mg | 10mg | 7× |
