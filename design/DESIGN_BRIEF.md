# Design brief — Grocery Basket Nutrition PWA

Paste everything below into the design tool. Attach `design/sample-report.json`
alongside it — it is the real data contract, not a mock.

---

## What you are designing

A **mobile-first installable PWA** that reports the nutrient composition of
groceries **purchased** by one household at a Belgian supermarket (Delhaize),
reconstructed by OCR-ing paper receipts.

It is an **honesty-first data product**. The single hardest design problem is
this: the underlying data is incomplete and partly wrong, and the interface must
make that impossible to miss **without making the app feel broken or useless**.
Today only 15.6% of purchase lines are fully usable. A conventional dashboard
would render that as confident numbers and would be lying.

## The one rule that overrides everything

This app describes **what was bought**, never **what was eaten**. Purchases are
not consumption: food is wasted, stored in the pantry, and meals are eaten out.

Therefore the design must **never**:

- present a value as an intake, a requirement, a deficiency, or an adequacy;
- use red/green traffic lights on nutrient values (a semaphore reads as
  "good/bad for you" no matter the caption);
- give dietary, medical, or supplement advice, or imply a diagnosis;
- show a single headline "score" for the household or for a person;
- render a number without its coverage figure directly beside it.

The previous version of this app told the family to take 1000–2000 IU of vitamin
D based on supermarket receipts. That is exactly the failure mode to design out.

## Data contract

Use `sample-report.json` **verbatim** — do not invent fields, do not rename them.
The real file has the same shape with ~2,275 items. Key parts:

| Path | Meaning |
|---|---|
| `status` | `Draft` \| `Beta` \| `Validated` — global trust state |
| `status_reasons[]` | plain-language reasons the status is not `Validated` |
| `disclaimer` | the purchases-≠-consumption text; must be visible, not hidden in a footer |
| `coverage.*` | the coverage chain: matched → quantity → usable → spend |
| `nutrients[name]` | `value`, `coverage_pct`, `reference`, `pct_of_reference`, `scored`, `top_contributors[]`, `dominated_by_single_item` |
| `nutrients_by_year["2025"]` | same shape, per year |
| `sensitivity_estimated_quantities[]` | `observed_only` vs `with_estimates` per nutrient |
| `quarantined[]` | mappings verified as wrong, each with a human-readable `reason` |
| `needs_review[]` | composite products matched to a single ingredient |
| `unresolved[]` | products that could not be matched or quantified |
| `items[]` | line-level rows with `state`, `qty_amount`, `qty_unit`, `declared_g`, `issues[]` |

`nutrients[n].scored === false` means the value **must not** be compared to the
reference — coverage is too low or no EU reference exists. Design a distinct,
non-alarming treatment for it.

Row `state` values, all of which need a clear visual identity:
`usable`, `quantity_unknown`, `volume_no_density`, `not_food_or_unmatched`,
`quarantined`, `no_food_record`, `receipt_metadata`.

## Screens

### 1. Overview
Trust state first. Status badge, the disclaimer, receipt counts (131 images /
127 unique / 88 analysed / 33 never read), the four-step coverage chain, the
covered period, and why the status is what it is.

### 2. Nutrients
Per 2,500 kcal of purchased food. Each row: name, value + unit, a bar with a
**reference marker** (EU Reg. 1169/2011 Annex XIII, rescaled to 2,500 kcal;
full scale = 200% of reference), and its coverage. Year filter (all / 2023 /
2024 / 2025). Tapping a row opens the top contributors with the evidence for
each match. Nutrients where one product supplies ≥25% must be flagged — that
figure is fragile.

### 3. Data quality
Receipt inventory, the sensitivity comparison (observed vs estimated
quantities — cholesterol swings +144%), quarantined mappings with reasons, and
the review queue. This screen is a first-class destination, not a settings page.

### 4. Purchases
Line-level list. Search, filter by state, and for each row: product name as
printed, what it was matched to, quantity **or an explicit "unknown"**, price,
and why it is or is not counted. Cards on mobile, table on desktop.

### 5. Product detail
Printed name, normalised name, quantity and how it was derived
(`label_single` / `label_multipack` / estimate / unknown), the official food
record, nutrients contributed, match confidence, and any issues.

### 6. Scan a receipt — NEW
The user photographs a paper receipt with the phone:

1. **Camera** — viewfinder with an alignment guide for a long, narrow thermal
   receipt; torch toggle; guidance for glare, folds and cropping.
2. **Preview** — retake or accept; multi-shot for receipts too long for one frame.
3. **Processing** — a real progress state; OCR is slow and may fail.
4. **Review & correct** — the extracted lines, **editable**. This is the most
   important screen in the flow: OCR gets product names, prices and quantities
   wrong, and the user is the only one who can fix it. Design for fast
   correction on a phone — big tap targets, inline edit, per-line confidence,
   flag-for-later.
5. **Result** — what was added, what needs review, and the effect on coverage.

Also design: offline capture queued for later, low-quality-image rejection,
duplicate-receipt detection ("you already added this one"), and total-mismatch
warning (parsed lines don't sum to the printed total).

## Languages

Italian, French, English — switchable, persisted. **French and Italian run
20–35% longer than English**; design every label, badge, bottom-nav item and
chart annotation to survive that without truncating or wrapping to three lines.
Bottom-nav labels must work at the longest of the three.

Note: receipt *content* is French and Dutch (`PAIN DE VIANDE`, `HET TRAAGSTE
BROOD`) and is **never translated** — it is printed evidence. Only interface
text is localised. Show product names in a way that makes clear they are raw
receipt text, not app copy.

## Constraints

- **Mobile-first at 390×844**, working up to 1440. Bottom nav on phone, top tabs
  or sidebar on desktop. Respect safe-area insets.
- Installable PWA: needs an icon, a splash/launch identity, and an offline state.
- **Light and dark mode**, both deliberately designed.
- **No horizontal page scroll ever.** Wide content scrolls inside its own container.
- Numbers use tabular figures in columns; proportional figures for large standalone values.
- WCAG AA. Identity must never rest on colour alone — pair every status colour
  with an icon and a word.
- **Self-contained**: no external fonts, no CDN, no remote images. System sans only.
- The whole thing is generated by a Python script into a static file — so ship
  **tokens and component specs**, not a framework-specific implementation.

## Deliverables

1. All six screens, phone and desktop, light and dark.
2. Design tokens (colour, type scale, spacing, radii, elevation) as CSS custom properties.
3. Component specs: status badge, stat tile, coverage meter, nutrient row with
   reference marker, state chip, sensitivity pair, editable OCR line, camera overlay.
4. The three trust states (`Draft` / `Beta` / `Validated`) shown as real screens.
5. Empty, loading, error and offline states.
6. A one-screen summary of how you solved the core problem: **communicating low
   confidence without making the product feel worthless.**

## What already exists

A working build lives in `public/index.html` (Python-generated, vanilla JS, no
build step). Current palette is a validated colourblind-safe set:
blue `#2a78d6` / orange `#eb6834` on `#fcfcfb`, dark steps `#3987e5` / `#d95926`
on `#1a1a19`. You may replace it — if you do, keep it colourblind-safe and state
the contrast ratios.
