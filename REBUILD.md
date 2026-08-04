# Paniere — rebuild + PWA

Ricostruzione della parte analitica e interfaccia PWA mobile-first.
**Nessuna dipendenza esterna**: solo la standard library di Python 3. Non servono
`pyfooda`, `pandas`, `numpy`, né una API key.

## Avvio

```bash
python3 -m skills.serve          # build + server + apre il browser
```

Poi apri **http://127.0.0.1:8791/index.html**. Ctrl-C per fermare.

Opzioni: `--port 9000`, `--no-open`, `--no-build` (serve quello che c'è già in `public/`).
Se la porta è occupata ne cerca automaticamente una libera.

### Passi separati

```bash
python3 -m skills.rebuild        # → public/report.json
python3 -m skills.report_html    # → public/index.html + manifest + service worker
open public/index.html           # funziona anche da file:// (ma non è installabile)
```

L'output è **riproducibile al byte**: due esecuzioni consecutive danno lo stesso file.

### Deep link

`?lang=en|fr|it` · `?theme=light|dark` · `?nut=Sodium` · `#overview|nutrients|quality|purchases|scan`

## Da dove vengono i dati

| Input | Ruolo |
|---|---|
| `data/purchases_enriched.csv` | righe di scontrino dello snapshot OCR legacy |
| `skills/food_table.json` | 124 profili nutrizionali per-100 g estratti dal report legacy |
| `skills/i18n.json` | 217 stringhe × EN/FR/IT, estratte dal progetto di design |

`food_table.json` è uno **snapshot congelato** di pyfooda, non una fonte
ufficiale: va sostituito con CIQUAL 2025 e USDA FoodData Central. Fino ad allora
lo stato resta `Draft`.

## Interfaccia

Implementa il progetto Claude Design *"Grocery Basket Nutrition PWA"*
(`Paniere.dc.html`) in JS vanilla — nessun framework, nessun build step,
nessun font o CDN esterno.

Cinque schermate: **Panoramica · Nutrienti · Qualità · Acquisti · Scansiona**,
più il pannello di dettaglio nutriente e prodotto.

Regole del sistema di design che l'implementazione rispetta:

- **Raggio 0 ovunque**, otturatore incluso. Filetti, mai ombre.
- **Non esiste un token per buono / attenzione / cattivo.** Il semaforo vietato
  non è scoraggiato, è *non disponibile*: chi verrà dopo non può prendere un
  verde senza aggiungere un token e accorgersi del perché non c'è.
- L'incertezza è **texture** (tratteggio a 135°), mai colore.
- L'asse dei nutrienti va da 0 al **200% del riferimento UE**, quindi la tacca
  è sempre al 50% e l'occhio impara un solo punto di riferimento.
- Il rosso (`--pn-accent`) indica struttura, azioni e verdetti **sui dati** —
  mai un verdetto sul cibo. Solo la quarantena è rossa.
- Il testo degli scontrini è **prova**: monospazio in riquadro, mai tradotto.

Quattro stati della riga nutriente: pieno (copertura ≥80%) · tratteggiato
(<80%, stessa lunghezza, meno certezza) · troncato e segnalato (oltre il 200%,
un prodotto ≥25%) · nessun riferimento (nessuna barra).

## Cosa cambia rispetto a `skills/nutrition_report.py`

| Legacy | Rebuild |
|---|---|
| 4 coppie di immagini identiche contate due volte | collassate, 130 righe rimosse |
| totali/punti fedeltà/pagamenti contati come prodotti | classificati `receipt_metadata` (17 righe) |
| quantità sconosciuta → 100 g silenziosi | resta sconosciuta, esce dai totali, abbassa la copertura |
| peso stimato da prezzo o peso tipico | solo quantità leggibile in etichetta; le stime finiscono nel pannello sensibilità |
| ml trattati come g | i volumi restano volumi (`volume_no_density`) |
| nutrienti soppressi se > 5× DRV | nessuna soppressione; i contributori dominanti vengono segnalati |
| interi scontrini eliminati con regola IQR | nessuna eliminazione statistica |
| riferimenti non standard (proteine 160 g) | RI/NRV UE Reg. 1169/2011 All. XIII riscalati a 2.500 kcal |
| `%DRV` con semaforo rosso/verde | densità vs riferimento, senza semaforo |
| stringhe OCR in `innerHTML` senza escaping | tutto passa da `esc()`, più CSP |
| consigli su integratori iniettati a mano | rimossi |
| solo italiano | EN / FR / IT, con selettore persistito |

## Quantità: come viene letta

Prima i multipack, poi il peso singolo, così `6X33CL` non diventa mai `33 cl`:

- `6X33CL SCH GINGER` → 1980 ml (volume, non massa)
- `190G THIN ROMARIN` → 190 g
- `40G DLL PATE NOI` → 40 g (il legacy scriveva 400 g)
- `MINT GRENAILLES 50` → sconosciuta (nessuna unità di misura)

## Abbinamenti in quarantena

10 abbinamenti verificati come sbagliati, esclusi dai calcoli e mostrati con la
motivazione nella scheda Qualità — fra cui `PIZZA MOZZA PESTO → PESTO` e
`DES DE FILET THAI → THAI TEA`. Vedi `QUARANTINE` in `skills/rebuild.py`.

## Scansiona

La cattura della foto è **reale** (`<input capture="environment">`, più scatti
per gli scontrini lunghi). Non c'è un backend OCR in questa build, quindi le
righe della schermata "Correggi" sono di esempio: il flusso è reale, il testo no.
Per renderla operativa serve un endpoint che riceva le immagini — vedi le note
sull'architettura nel brief di design.

## Stati

| Stato | Significato |
|---|---|
| `Draft` | copertura insufficiente o revisioni pendenti — non usare per conclusioni |
| `Beta` | pipeline completa, copertura media |
| `Validated` | soglie raggiunte e abbinamenti verificati su fonti ufficiali |

`Draft` è lo stato previsto per molto tempo. Non è un avviso e non c'è nulla da attendere.

## Verifiche eseguite

- **XSS**: `<img src=x onerror=alert(1)><script>alert(2)</script>` iniettato come
  nome prodotto → sopravvive solo come dato, nessun markup attivo.
- **Riproducibilità**: due build consecutive, hash identico.
- **Palette**: validata sul validator del design system, PASS in chiaro e scuro.
- **Screenshot**: 390×940 e 1440×980, EN/FR/IT, chiaro e scuro, tutte le schermate.

## Pubblicazione

`.github/workflows/deploy-pages.yml` pubblica ancora `data/`. Per mettere online
questa demo va cambiato in `path: public`.
