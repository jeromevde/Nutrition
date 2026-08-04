# Paniere — Handover

**[English](#english) · [Français](#français) · [Italiano](#italiano)**

A rebuild of the nutrition pipeline plus a mobile-first PWA.
Reconstruction de la chaîne nutritionnelle et PWA mobile-first.
Ricostruzione della pipeline nutrizionale e PWA mobile-first.

```bash
python3 -m skills.serve      # → http://127.0.0.1:8791/index.html
```

No dependencies · Aucune dépendance · Nessuna dipendenza — Python 3 standard library only.

---

# English

## What this is

The repository turns Belgian supermarket receipts (Delhaize) into a report on the
nutrient composition of the groceries **bought**. This handover covers a rebuild of
the analysis layer and a new interface.

The one rule the whole project rests on: **this measures what was purchased, never
what was eaten.** Waste, pantry stock, meals eaten out and the two retailers not yet
ingested (Carrefour, Colruyt) are all unaccounted for.

## Run it

```bash
python3 -m skills.serve                # build + local server + opens the browser
python3 -m skills.serve --port 9000    # another port (it also auto-picks a free one)
python3 -m skills.serve --no-build     # serve whatever is already in public/
```

Then open **http://127.0.0.1:8791/index.html**. Ctrl-C stops it.

Separate steps:

```bash
python3 -m skills.rebuild        # → public/report.json
python3 -m skills.report_html    # → public/index.html + manifest + service worker
open public/index.html           # works from file:// too, but is not installable
```

Serving over `http://127.0.0.1` rather than `file://` is what makes the service
worker register and the install-as-app prompt appear.

Deep links: `?lang=en|fr|it` · `?theme=light|dark` · `?nut=Sodium` ·
`?scan=camera|preview|processing|review|result` · `#overview|nutrients|quality|purchases|scan`

The build is **byte-reproducible**: two consecutive runs produce an identical file.

## What was found in the existing data

Every figure below was verified against the actual files, not taken from a report.

| Finding | Evidence |
|---|---|
| 4 pairs of receipt images are byte-identical and were **counted twice** | SHA-256 over `data/delhaize/*.jpg`; all 8 files appear in the legacy per-trip output |
| 33 receipt images were **never passed to OCR** | contiguous from 2025-08-14 onward — the batch was simply never re-run, not an OCR failure |
| 6 OCR outputs are empty but were treated as successful | header-only CSVs |
| Quantity was unknown on 22.4% of matched rows and silently became **100 g** | `DEFAULT_GRAMS = 100` in the legacy report generator |
| ~90% of barcodes are **fabricated** | 98.8% of rows carry a barcode string; only 10.0% pass a GTIN check digit |
| Receipt totals, loyalty points and payment lines were counted as **products** | inflated total spend from €9,098.67 to €22,891 — one line was a 6,096-point loyalty balance |
| Verified wrong mappings | ginger ale → ginger root (and 1.98 L counted as 1,980 g of spice); rosemary crackers → pure rosemary; meatloaf → bread; fresh mint → crème-de-menthe; a 40 g pack recorded as 400 g; **whole pizza → pesto sauce**; **diced meat fillet → Thai tea** |
| A generic `5 × DRV` cap silently deleted nutrients | removed salt's sodium while keeping everything else |
| Reference values matched no published standard | protein 160 g, sodium 1500 mg — neither EU RIs nor US DVs |
| The report injected **supplement advice** from purchase data | "1 000–2 000 IU recommended for the whole household" |
| Documented pipeline modules do not exist | `build_mapping.py`, `matcher.py`, `report_verifier.py` are referenced by README and AGENTS.md but absent — the legacy numbers cannot be regenerated |

## What changed

| Legacy | Rebuild |
|---|---|
| duplicate receipts counted twice | collapsed — 130 rows removed |
| totals / loyalty / payment counted as products | classified `receipt_metadata` (17 rows) |
| unknown quantity → silent 100 g | stays unknown, leaves the totals, lowers coverage |
| weight guessed from price or typical unit weight | label-readable quantity only; estimates go to a sensitivity panel |
| millilitres treated as grams | volumes stay volumes (`volume_no_density`) |
| nutrients suppressed above 5 × DRV | no suppression; dominant contributors are flagged instead |
| whole trips deleted by an IQR rule | no statistical deletion |
| non-standard reference values | EU Reg. 1169/2011 Annex XIII RIs/NRVs rescaled to 2,500 kcal |
| `%DRV` with a red/green semaphore | density against a reference, no semaphore |
| OCR text into `innerHTML` unescaped | everything through `esc()`, plus a CSP |
| hand-written supplement advice | removed |
| Italian only | EN / FR / IT with a persisted switcher |

## Where the numbers stand

| | |
|---|---|
| Receipt images | 131 → **127** unique (4 duplicate pairs) |
| OCR outputs | 98 files, 6 empty, 33 images never read |
| Receipts in the analysis | **88** · 2023-01-10 → 2025-07-22 |
| Rows | 2,422 raw → 130 duplicates → 17 receipt-metadata → **2,275 product lines** |
| Matched to a food | **69.9%** |
| Quantity readable on the label | **22.4%** of matched |
| Usable in the calculation | **15.6%** (52.6% if estimated weights were re-included) |
| Spend represented | **12.6%** — €1,145.73 of €9,098.67 |
| Quarantined mappings | 10 · review queue 4 · unresolved products 120 |
| Trust state | **Draft** |

Effect on the 2025 figures, per 2,500 kcal:

| Nutrient | Legacy | Rebuild | |
|---|---:|---:|---:|
| Sodium | 2,770 mg | 1,446 mg | −48% |
| Protein | 124.9 g | 75.8 g | −39% |
| Total fat | 100.1 g | 80.9 g | −19% |
| Calcium | 982 mg | 828 mg | −16% |
| Iron | 21.2 mg | 27.9 mg | +32% |

Sodium halves because the `5 × DRV` cap that deleted salt's sodium is gone and the
mis-mapped "salt" line is quarantined. Protein falls because invented weights are gone.

**15.6% is not a regression.** It is what was underneath the automatic 100 g.

## The interface

Implements the Claude Design project *"Grocery Basket Nutrition PWA"*
(`design/imported/Paniere.dc.html`) in vanilla JS — no framework, no build step,
no external fonts or CDNs.

Five screens: **Overview · Nutrients · Data quality · Purchases · Scan**, plus
nutrient and product detail sheets. Light and dark, EN/FR/IT, installable as a PWA.

Design rules the implementation honours:

- **Radius 0 everywhere**, shutter included. Rules, never shadows.
- **No token exists for good / warning / bad.** The forbidden semaphore is not
  discouraged, it is *unavailable* — a later contributor cannot reach for a green
  without adding a token and noticing why there isn't one.
- Uncertainty is **texture** (135° hatching), never colour.
- The nutrient axis runs 0 → **200% of the EU reference**, so the marker is always
  at 50% and the eye learns one landmark.
- Red means structure, actions and verdicts about **the data** — never about food.
  Only quarantine is red.
- Receipt text is **evidence**: boxed monospace, never translated.

Four nutrient-row states: solid (coverage ≥80%) · hatched (<80%, same length, less
certainty) · clamped and flagged (over 200%, one product ≥25%) · no bar at all when
no EU reference exists.

## What is real and what is not

The photo capture in **Scan** is real — `<input capture="environment">`, multiple
frames for long receipts, preview. **There is no OCR backend in this build**, so the
lines on the "Correct" screen are examples: the flow is real, the text is not.

Making it work needs an endpoint that receives the images. Putting an API key in the
browser is not an option — anyone could read it and spend against it.

## File map

| Path | |
|---|---|
| `skills/rebuild.py` | the analysis — dedup, quantity parsing, coverage, references |
| `skills/report_html.py` | the PWA generator |
| `skills/serve.py` | build + local server |
| `skills/food_table.json` | 124 per-100 g profiles recovered from the legacy report |
| `skills/i18n.json` | 217 strings × EN/FR/IT |
| `public/` | generated output — `index.html`, `report.json`, manifest, service worker |
| `design/DESIGN_BRIEF.md` | the brief given to the design tool |
| `design/sample-report.json` | sanitised sample data for designers |
| `design/imported/Paniere.dc.html` | the design project as imported |
| `REBUILD.md` | shorter operational notes (Italian) |

`skills/food_table.json` is a **frozen snapshot** of pyfooda, not an official source.
It must be replaced by CIQUAL 2025 and USDA FoodData Central. Until then the state
stays `Draft`.

## Checks that were run

- **XSS**: `<img src=x onerror=alert(1)><script>alert(2)</script>` injected as a
  product name and the site regenerated — it survives only as data, no live markup.
- **Reproducibility**: two consecutive builds, identical hash.
- **State filters**: all seven reconcile — every chip count matches the rows listed.
- **Receipt inventory reconciles to zero**: 131 − 4 = 127; 39 outside the analysis =
  33 never read + 6 empty + 0 unexplained.
- **Palette**: validated colourblind-safe in light and dark.
- **`node --check`** on the generated app JS.
- **Screenshots**: 390×940 and 1440×980, all screens, three languages, both themes.

## What is left

1. **The 33 unread receipts** — a whole year from August 2025. Needs an OpenRouter
   API key; no code change. Highest impact on the numbers.
2. **Replace pyfooda** with CIQUAL 2025 and USDA FoodData Central. Required to leave
   `Draft`.
3. **An OCR endpoint** to make Scan real.

Out of scope by decision: privacy and publication. `.github/workflows/deploy-pages.yml`
still publishes `data/` — including raw receipt images. Change it to `path: public`
before putting anything online.

---

# Français

## De quoi il s'agit

Le dépôt transforme des tickets de caisse belges (Delhaize) en un rapport sur la
composition nutritionnelle des courses **achetées**. Ce document couvre une
reconstruction de la couche d'analyse et une nouvelle interface.

La règle sur laquelle repose tout le projet : **on mesure ce qui a été acheté, jamais
ce qui a été mangé.** Pertes, stock de réserve, repas pris dehors et les deux enseignes
pas encore intégrées (Carrefour, Colruyt) ne sont pas pris en compte.

## Lancer l'application

```bash
python3 -m skills.serve                # build + serveur local + ouvre le navigateur
python3 -m skills.serve --port 9000    # autre port (un port libre est choisi seul)
python3 -m skills.serve --no-build     # sert ce qui est déjà dans public/
```

Puis **http://127.0.0.1:8791/index.html**. Ctrl-C pour arrêter.

Étapes séparées :

```bash
python3 -m skills.rebuild        # → public/report.json
python3 -m skills.report_html    # → public/index.html + manifest + service worker
open public/index.html           # fonctionne aussi en file://, mais non installable
```

Servir en `http://127.0.0.1` plutôt qu'en `file://` est ce qui permet au service
worker de s'enregistrer et à l'invite d'installation d'apparaître.

Liens directs : `?lang=en|fr|it` · `?theme=light|dark` · `?nut=Sodium` ·
`?scan=camera|preview|processing|review|result` · `#overview|nutrients|quality|purchases|scan`

Le build est **reproductible à l'octet** : deux exécutions donnent un fichier identique.

## Ce qui a été trouvé dans les données

Chaque chiffre ci-dessous a été vérifié sur les fichiers réels.

| Constat | Preuve |
|---|---|
| 4 paires d'images de tickets sont identiques à l'octet et étaient **comptées deux fois** | SHA-256 sur `data/delhaize/*.jpg` ; les 8 fichiers figurent dans la sortie legacy |
| 33 images n'ont **jamais été passées à l'OCR** | contiguës depuis le 14/08/2025 — le traitement n'a jamais été relancé, ce n'est pas un échec d'OCR |
| 6 sorties OCR sont vides mais étaient considérées réussies | CSV réduits à l'en-tête |
| La quantité était inconnue sur 22,4 % des lignes associées et devenait **100 g** en silence | `DEFAULT_GRAMS = 100` |
| ~90 % des codes-barres sont **inventés** | 98,8 % des lignes portent un code ; seuls 10,0 % passent la clé de contrôle GTIN |
| Totaux, points de fidélité et paiements comptés comme **produits** | dépense totale gonflée de 9 098,67 € à 22 891 € — une ligne était un solde de 6 096 points |
| Correspondances vérifiées comme fausses | ginger ale → gingembre frais (et 1,98 L comptés comme 1 980 g d'épice) ; crackers au romarin → romarin pur ; pain de viande → pain ; menthe fraîche → crème de menthe ; un paquet de 40 g enregistré à 400 g ; **pizza entière → sauce pesto** ; **filet de viande en dés → thé thaï** |
| Un plafond générique `5 × AJR` supprimait des nutriments en silence | retirait le sodium du sel en gardant le reste |
| Les valeurs de référence ne correspondaient à aucun standard publié | protéines 160 g, sodium 1500 mg — ni RI européens ni DV américains |
| Le rapport injectait un **conseil sur les compléments** | « 1 000–2 000 UI recommandées pour tout le foyer » |
| Des modules documentés n'existent pas | `build_mapping.py`, `matcher.py`, `report_verifier.py` sont cités par le README mais absents — les chiffres legacy ne sont pas reproductibles |

## Ce qui a changé

| Legacy | Reconstruction |
|---|---|
| tickets en double comptés deux fois | fusionnés — 130 lignes retirées |
| totaux / fidélité / paiement comptés comme produits | classés `receipt_metadata` (17 lignes) |
| quantité inconnue → 100 g silencieux | reste inconnue, sort des totaux, fait baisser la couverture |
| poids deviné d'après le prix ou un poids typique | uniquement la quantité lisible sur l'étiquette ; les estimations vont dans un panneau de sensibilité |
| millilitres traités comme des grammes | les volumes restent des volumes (`volume_no_density`) |
| nutriments supprimés au-delà de 5 × AJR | aucune suppression ; les contributeurs dominants sont signalés |
| tickets entiers supprimés par une règle IQR | aucune suppression statistique |
| valeurs de référence non standard | RI/VNR du Règl. UE 1169/2011 annexe XIII remis à l'échelle de 2 500 kcal |
| `%AJR` avec feu rouge/vert | densité face à une référence, sans feu tricolore |
| texte OCR injecté dans `innerHTML` | tout passe par `esc()`, plus une CSP |
| conseil sur les compléments écrit à la main | supprimé |
| italien uniquement | EN / FR / IT avec sélecteur mémorisé |

## Où en sont les chiffres

| | |
|---|---|
| Images de tickets | 131 → **127** uniques (4 paires en double) |
| Sorties OCR | 98 fichiers, 6 vides, 33 images jamais lues |
| Tickets dans l'analyse | **88** · 10/01/2023 → 22/07/2025 |
| Lignes | 2 422 brutes → 130 doublons → 17 lignes de ticket → **2 275 lignes produit** |
| Associées à un aliment | **69,9 %** |
| Quantité lisible sur l'étiquette | **22,4 %** des lignes associées |
| Exploitables dans le calcul | **15,6 %** (52,6 % avec les poids estimés) |
| Dépense représentée | **12,6 %** — 1 145,73 € sur 9 098,67 € |
| Correspondances en quarantaine | 10 · file de révision 4 · produits non résolus 120 |
| État de confiance | **Brouillon** |

Effet sur les chiffres 2025, pour 2 500 kcal :

| Nutriment | Legacy | Reconstruit | |
|---|---:|---:|---:|
| Sodium | 2 770 mg | 1 446 mg | −48 % |
| Protéines | 124,9 g | 75,8 g | −39 % |
| Matières grasses | 100,1 g | 80,9 g | −19 % |
| Calcium | 982 mg | 828 mg | −16 % |
| Fer | 21,2 mg | 27,9 mg | +32 % |

Le sodium est divisé par deux parce que le plafond `5 × AJR` qui supprimait celui du
sel a disparu et que la ligne « sel » mal associée est en quarantaine. Les protéines
chutent parce que les poids inventés ont disparu.

**15,6 % n'est pas une régression.** C'est ce qu'il y avait sous les 100 g automatiques.

## L'interface

Implémente le projet Claude Design *« Grocery Basket Nutrition PWA »*
(`design/imported/Paniere.dc.html`) en JS vanilla — aucun framework, aucune étape de
build, aucune police ni CDN externe.

Cinq écrans : **Aperçu · Nutriments · Qualité · Achats · Scanner**, plus les fiches
détaillées nutriment et produit. Clair et sombre, EN/FR/IT, installable en PWA.

Règles de design respectées :

- **Rayon 0 partout**, déclencheur compris. Des filets, jamais d'ombres.
- **Aucun jeton n'existe pour bon / attention / mauvais.** Le feu tricolore interdit
  n'est pas découragé, il est *indisponible* — un contributeur ultérieur ne peut pas
  saisir un vert sans ajouter un jeton et comprendre pourquoi il n'y en avait pas.
- L'incertitude est une **texture** (hachures à 135°), jamais une couleur.
- L'axe va de 0 à **200 % de la référence UE** : le repère est toujours à 50 % et
  l'œil apprend un seul point de repère.
- Le rouge signale la structure, les actions et les verdicts sur **les données** —
  jamais sur les aliments. Seule la quarantaine est rouge.
- Le texte des tickets est une **preuve** : monospace encadré, jamais traduit.

Quatre états de ligne : plein (couverture ≥80 %) · hachuré (<80 %, même longueur,
moins de certitude) · tronqué et signalé (au-delà de 200 %, un produit ≥25 %) ·
aucune barre quand aucune référence UE n'existe.

## Ce qui est réel et ce qui ne l'est pas

La prise de photo dans **Scanner** est réelle — `<input capture="environment">`,
plusieurs images pour les tickets longs, aperçu. **Il n'y a pas de backend OCR dans
cette version** : les lignes de l'écran « Corriger » sont des exemples. Le parcours
est réel, le texte non.

Le rendre opérationnel demande un point d'accès qui reçoive les images. Mettre une clé
API dans le navigateur n'est pas envisageable — n'importe qui la lirait.

## Carte des fichiers

| Chemin | |
|---|---|
| `skills/rebuild.py` | l'analyse — dédoublonnage, quantités, couverture, références |
| `skills/report_html.py` | générateur de la PWA |
| `skills/serve.py` | build + serveur local |
| `skills/food_table.json` | 124 profils pour 100 g récupérés du rapport legacy |
| `skills/i18n.json` | 217 chaînes × EN/FR/IT |
| `public/` | sortie générée |
| `design/DESIGN_BRIEF.md` | le brief remis à l'outil de design |
| `design/sample-report.json` | données d'exemple assainies |
| `design/imported/Paniere.dc.html` | le projet de design importé |
| `REBUILD.md` | notes opérationnelles plus courtes (italien) |

`skills/food_table.json` est un **instantané figé** de pyfooda, pas une source
officielle. Il doit être remplacé par CIQUAL 2025 et USDA FoodData Central. D'ici là
l'état reste `Brouillon`.

## Contrôles effectués

- **XSS** : `<img src=x onerror=alert(1)><script>alert(2)</script>` injecté comme nom
  de produit puis site régénéré — la charge ne survit que comme donnée, aucun balisage actif.
- **Reproductibilité** : deux builds consécutifs, empreinte identique.
- **Filtres d'état** : les sept concordent — chaque compteur correspond aux lignes listées.
- **L'inventaire des tickets tombe juste** : 131 − 4 = 127 ; 39 hors analyse = 33 jamais
  lus + 6 vides + 0 inexpliqués.
- **Palette** : validée pour les daltonismes, en clair et en sombre.
- **`node --check`** sur le JS généré.
- **Captures** : 390×940 et 1440×980, tous les écrans, trois langues, deux thèmes.

## Ce qui reste

1. **Les 33 tickets non lus** — une année entière depuis août 2025. Nécessite une clé
   API OpenRouter, aucun changement de code. Plus fort impact sur les chiffres.
2. **Remplacer pyfooda** par CIQUAL 2025 et USDA FoodData Central. Nécessaire pour
   sortir de `Brouillon`.
3. **Un point d'accès OCR** pour rendre Scanner opérationnel.

Hors périmètre par décision : confidentialité et publication.
`.github/workflows/deploy-pages.yml` publie encore `data/` — images de tickets comprises.
Passer à `path: public` avant toute mise en ligne.

---

# Italiano

## Di cosa si tratta

Il repository trasforma scontrini di supermercati belgi (Delhaize) in un report sulla
composizione nutrizionale della spesa **acquistata**. Questo documento copre una
ricostruzione del livello di analisi e una nuova interfaccia.

La regola su cui poggia tutto il progetto: **si misura ciò che è stato comprato, mai
ciò che è stato mangiato.** Scarti, scorte in dispensa, pasti fuori casa e i due
negozi non ancora inclusi (Carrefour, Colruyt) non sono considerati.

## Avviare l'app

```bash
python3 -m skills.serve                # build + server locale + apre il browser
python3 -m skills.serve --port 9000    # altra porta (ne cerca comunque una libera)
python3 -m skills.serve --no-build     # serve quello che c'è già in public/
```

Poi **http://127.0.0.1:8791/index.html**. Ctrl-C per fermare.

Passi separati:

```bash
python3 -m skills.rebuild        # → public/report.json
python3 -m skills.report_html    # → public/index.html + manifest + service worker
open public/index.html           # funziona anche da file://, ma non è installabile
```

Servire su `http://127.0.0.1` invece che da `file://` è ciò che permette al service
worker di registrarsi e all'invito di installazione di comparire.

Deep link: `?lang=en|fr|it` · `?theme=light|dark` · `?nut=Sodium` ·
`?scan=camera|preview|processing|review|result` · `#overview|nutrients|quality|purchases|scan`

La build è **riproducibile al byte**: due esecuzioni danno un file identico.

## Cosa è emerso dai dati

Ogni cifra qui sotto è stata verificata sui file reali.

| Rilievo | Prova |
|---|---|
| 4 coppie di immagini sono identiche al byte ed erano **contate due volte** | SHA-256 su `data/delhaize/*.jpg`; tutti e 8 i file compaiono nell'output legacy |
| 33 immagini non sono **mai passate all'OCR** | contigue dal 14/08/2025 — il batch non è mai stato rilanciato, non è un errore di OCR |
| 6 output OCR sono vuoti ma erano considerati riusciti | CSV con la sola intestazione |
| La quantità era sconosciuta sul 22,4% delle righe abbinate e diventava **100 g** in silenzio | `DEFAULT_GRAMS = 100` |
| Circa il **90% dei codici a barre è inventato** | il 98,8% delle righe porta un codice; solo il 10,0% supera la cifra di controllo GTIN |
| Totali, punti fedeltà e pagamenti contati come **prodotti** | spesa totale gonfiata da 9.098,67 € a 22.891 € — una riga era un saldo di 6.096 punti |
| Abbinamenti verificati come sbagliati | ginger ale → zenzero fresco (e 1,98 L contati come 1.980 g di spezia); crackers al rosmarino → rosmarino puro; pain de viande → pane; menta fresca → crème-de-menthe; una confezione da 40 g registrata come 400 g; **pizza intera → salsa al pesto**; **filetto di carne a dadini → tè thailandese** |
| Un tappo generico `5 × DRV` cancellava nutrienti in silenzio | toglieva il sodio del sale tenendo tutto il resto |
| I valori di riferimento non corrispondevano a nessuno standard pubblicato | proteine 160 g, sodio 1500 mg — né RI europei né DV statunitensi |
| Il report iniettava un **consiglio sugli integratori** | «1.000–2.000 UI raccomandate per tutta la famiglia» |
| Moduli documentati che non esistono | `build_mapping.py`, `matcher.py`, `report_verifier.py` sono citati da README e AGENTS.md ma assenti — i numeri legacy non sono riproducibili |

## Cosa è cambiato

| Legacy | Ricostruzione |
|---|---|
| scontrini duplicati contati due volte | collassati — 130 righe rimosse |
| totali / fedeltà / pagamenti contati come prodotti | classificati `receipt_metadata` (17 righe) |
| quantità sconosciuta → 100 g silenziosi | resta sconosciuta, esce dai totali, abbassa la copertura |
| peso stimato dal prezzo o da un peso tipico | solo quantità leggibile in etichetta; le stime finiscono in un pannello di sensibilità |
| millilitri trattati come grammi | i volumi restano volumi (`volume_no_density`) |
| nutrienti soppressi oltre 5 × DRV | nessuna soppressione; i contributori dominanti vengono segnalati |
| interi scontrini eliminati con regola IQR | nessuna eliminazione statistica |
| valori di riferimento non standard | RI/NRV Reg. UE 1169/2011 All. XIII riscalati a 2.500 kcal |
| `%DRV` con semaforo rosso/verde | densità rispetto a un riferimento, senza semaforo |
| testo OCR in `innerHTML` senza escaping | tutto passa da `esc()`, più una CSP |
| consiglio sugli integratori scritto a mano | rimosso |
| solo italiano | EN / FR / IT con selettore memorizzato |

## A che punto sono i numeri

| | |
|---|---|
| Immagini di scontrini | 131 → **127** uniche (4 coppie duplicate) |
| Output OCR | 98 file, 6 vuoti, 33 immagini mai lette |
| Scontrini nell'analisi | **88** · 10/01/2023 → 22/07/2025 |
| Righe | 2.422 grezze → 130 duplicate → 17 righe di scontrino → **2.275 righe prodotto** |
| Abbinate a un alimento | **69,9%** |
| Quantità leggibile in etichetta | **22,4%** delle righe abbinate |
| Utilizzabili nel calcolo | **15,6%** (52,6% reintegrando i pesi stimati) |
| Spesa rappresentata | **12,6%** — 1.145,73 € su 9.098,67 € |
| Abbinamenti in quarantena | 10 · coda di revisione 4 · prodotti irrisolti 120 |
| Stato di fiducia | **Bozza** |

Effetto sui valori 2025, per 2.500 kcal:

| Nutriente | Legacy | Ricostruito | |
|---|---:|---:|---:|
| Sodio | 2.770 mg | 1.446 mg | −48% |
| Proteine | 124,9 g | 75,8 g | −39% |
| Grassi totali | 100,1 g | 80,9 g | −19% |
| Calcio | 982 mg | 828 mg | −16% |
| Ferro | 21,2 mg | 27,9 mg | +32% |

Il sodio si dimezza perché è sparito il tappo `5 × DRV` che cancellava quello del sale
e perché la riga «sale» mal abbinata è in quarantena. Le proteine crollano perché sono
spariti i pesi inventati.

**15,6% non è un peggioramento.** È quello che c'era sotto i 100 g automatici.

## L'interfaccia

Implementa il progetto Claude Design *«Grocery Basket Nutrition PWA»*
(`design/imported/Paniere.dc.html`) in JS vanilla — nessun framework, nessun build
step, nessun font o CDN esterno.

Cinque schermate: **Panoramica · Nutrienti · Qualità · Acquisti · Scansiona**, più i
pannelli di dettaglio nutriente e prodotto. Chiaro e scuro, EN/FR/IT, installabile
come PWA.

Regole di design rispettate:

- **Raggio 0 ovunque**, otturatore incluso. Filetti, mai ombre.
- **Non esiste un token per buono / attenzione / cattivo.** Il semaforo vietato non è
  scoraggiato, è *non disponibile* — chi verrà dopo non può prendere un verde senza
  aggiungere un token e accorgersi del perché non c'era.
- L'incertezza è **texture** (tratteggio a 135°), mai colore.
- L'asse dei nutrienti va da 0 al **200% del riferimento UE**: la tacca è sempre al
  50% e l'occhio impara un solo punto di riferimento.
- Il rosso indica struttura, azioni e verdetti sui **dati** — mai sul cibo. Solo la
  quarantena è rossa.
- Il testo degli scontrini è **prova**: monospazio in riquadro, mai tradotto.

Quattro stati della riga nutriente: pieno (copertura ≥80%) · tratteggiato (<80%,
stessa lunghezza, meno certezza) · troncato e segnalato (oltre il 200%, un prodotto
≥25%) · nessuna barra quando non esiste un riferimento UE.

## Cosa è reale e cosa no

La cattura foto in **Scansiona** è reale — `<input capture="environment">`, più scatti
per gli scontrini lunghi, anteprima. **In questa build non c'è un backend OCR**, quindi
le righe della schermata «Correggi» sono di esempio: il flusso è vero, il testo no.

Per renderla operativa serve un endpoint che riceva le immagini. Mettere una chiave API
nel browser non è un'opzione — chiunque la leggerebbe e la userebbe a tue spese.

## Mappa dei file

| Percorso | |
|---|---|
| `skills/rebuild.py` | l'analisi — deduplica, quantità, copertura, riferimenti |
| `skills/report_html.py` | generatore della PWA |
| `skills/serve.py` | build + server locale |
| `skills/food_table.json` | 124 profili per 100 g recuperati dal report legacy |
| `skills/i18n.json` | 217 stringhe × EN/FR/IT |
| `public/` | output generato |
| `design/DESIGN_BRIEF.md` | il brief consegnato allo strumento di design |
| `design/sample-report.json` | dati campione sanificati |
| `design/imported/Paniere.dc.html` | il progetto di design importato |
| `REBUILD.md` | note operative più brevi |

`skills/food_table.json` è uno **snapshot congelato** di pyfooda, non una fonte
ufficiale. Va sostituito con CIQUAL 2025 e USDA FoodData Central. Fino ad allora lo
stato resta `Bozza`.

## Verifiche eseguite

- **XSS**: `<img src=x onerror=alert(1)><script>alert(2)</script>` iniettato come nome
  prodotto e sito rigenerato — sopravvive solo come dato, nessun markup attivo.
- **Riproducibilità**: due build consecutive, hash identico.
- **Filtri di stato**: tutti e sette riconciliano — ogni contatore corrisponde alle
  righe elencate.
- **L'inventario scontrini torna a zero**: 131 − 4 = 127; 39 fuori analisi = 33 mai
  letti + 6 vuoti + 0 inspiegati.
- **Palette**: validata per i daltonismi, in chiaro e in scuro.
- **`node --check`** sul JS generato.
- **Screenshot**: 390×940 e 1440×980, tutte le schermate, tre lingue, entrambi i temi.

## Cosa resta

1. **I 33 scontrini mai letti** — un anno intero da agosto 2025. Serve una chiave API
   OpenRouter, nessuna modifica al codice. È l'intervento con l'impatto maggiore.
2. **Sostituire pyfooda** con CIQUAL 2025 e USDA FoodData Central. Necessario per
   uscire da `Bozza`.
3. **Un endpoint OCR** per rendere operativa la scansione.

Fuori scope per decisione: privacy e pubblicazione.
`.github/workflows/deploy-pages.yml` pubblica ancora `data/` — immagini degli scontrini
comprese. Va cambiato in `path: public` prima di mettere online qualsiasi cosa.
