#!/usr/bin/env python3
"""
skills.report_html — render public/report.json as the "Paniere" PWA.

Implements the Claude Design project "Grocery Basket Nutrition PWA"
(Paniere.dc.html) in vanilla JS: no framework, no build step, no external
fonts or CDNs. Python inlines the data and the string table; the browser does
the rest.

Design system (from §05 Tokens)
-------------------------------
* Radius 0 everywhere, including the shutter. Rules, never shadows.
* No token exists for good / warning / bad — the forbidden semaphore is
  unavailable rather than discouraged.
* Uncertainty is TEXTURE (135° hatching), never colour.
* Nutrient axis runs 0 → 200% of the EU reference, so the marker is always at
  50% and the eye learns one landmark.
* Red (--pn-accent) means structure, actions and *data* verdicts — never a
  verdict about food.

Run:  python3 -m skills.report_html
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "public"
REPORT_JSON = PUBLIC / "report.json"
I18N_JSON = Path(__file__).resolve().parent / "i18n.json"

MANIFEST = {
    "name": "Paniere — Delhaize basket",
    "short_name": "Paniere",
    "start_url": "./index.html",
    "scope": "./",
    "display": "standalone",
    "background_color": "#ec3013",
    "theme_color": "#ec3013",
    "icons": [{
        # The icon IS the coverage figure: a solid band over a hatched field,
        # in the ratio the report actually reports.
        "src": "data:image/svg+xml;charset=utf-8," + (
            "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 512 512'%3E"
            "%3Cdefs%3E%3Cpattern id='h' width='32' height='32' "
            "patternTransform='rotate(135)' patternUnits='userSpaceOnUse'%3E"
            "%3Crect width='11' height='32' fill='%23f3f2f2' opacity='.85'/%3E"
            "%3C/pattern%3E%3C/defs%3E"
            "%3Crect width='512' height='512' fill='%23ec3013'/%3E"
            "%3Crect x='64' y='168' width='384' height='70' fill='%23f3f2f2'/%3E"
            "%3Crect x='64' y='238' width='384' height='234' fill='url(%23h)'/%3E"
            "%3C/svg%3E"
        ),
        "sizes": "any",
        "type": "image/svg+xml",
        "purpose": "any",
    }],
}

SERVICE_WORKER = """\
/* Network-first on everything. A cached report shown under a fresh trust badge
   would be exactly the failure this app exists to prevent. */
const SHELL = 'paniere-v2';
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(
  caches.keys()
    .then(ks => Promise.all(ks.filter(k => k !== SHELL).map(k => caches.delete(k))))
    .then(() => self.clients.claim())
));
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  e.respondWith(
    fetch(e.request).then(res => {
      const copy = res.clone();
      caches.open(SHELL).then(c => c.put(e.request, copy));
      return res;
    }).catch(() => caches.match(e.request))
  );
});
"""

CSS = r"""
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;border-radius:0}
:root{
  --pn-bg:#f3f2f2;--pn-surface:#eae9e9;--pn-surface2:#e0dede;
  --pn-ink:#201e1d;--pn-ink2:#605d5d;--pn-ink3:#7d7979;
  --pn-rule:rgba(32,30,29,.18);--pn-rule2:rgba(32,30,29,.44);
  --pn-accent:#ec3013;--pn-accentText:#ae1800;--pn-track:#d7d3d3;
  --pn-hatch:repeating-linear-gradient(135deg,rgba(32,30,29,.9) 0 1.5px,transparent 1.5px 5px);
  --pn-hatch2:repeating-linear-gradient(135deg,rgba(32,30,29,.42) 0 1.5px,transparent 1.5px 5px);
  --pn-scrim:rgba(32,30,29,.55);
  color-scheme:light;
}
[data-t="dark"]{
  --pn-bg:#171615;--pn-surface:#211f1e;--pn-surface2:#2b2928;
  --pn-ink:#f3f2f2;--pn-ink2:#b8b3b1;--pn-ink3:#8a8583;
  --pn-rule:rgba(243,242,242,.20);--pn-rule2:rgba(243,242,242,.44);
  --pn-accent:#ff563c;--pn-accentText:#ff9783;--pn-track:#3a3736;
  --pn-hatch:repeating-linear-gradient(135deg,rgba(243,242,242,.9) 0 1.5px,transparent 1.5px 5px);
  --pn-hatch2:repeating-linear-gradient(135deg,rgba(243,242,242,.42) 0 1.5px,transparent 1.5px 5px);
  --pn-scrim:rgba(0,0,0,.66);
  color-scheme:dark;
}
html{-webkit-text-size-adjust:100%}
body{
  font-family:'Archivo',system-ui,-apple-system,'Segoe UI',sans-serif;
  background:var(--pn-bg);color:var(--pn-ink);font-size:12.5px;line-height:1.5;
  padding-bottom:calc(56px + env(safe-area-inset-bottom));
  overflow-x:hidden;
}
.tab{font-variant-numeric:tabular-nums}
.mono{font-family:ui-monospace,Menlo,Consolas,monospace;letter-spacing:.02em}
.micro{font:800 9.5px/1.25 'Archivo',system-ui;letter-spacing:.09em;text-transform:uppercase;color:var(--pn-ink3)}
.wrap{max-width:760px;margin:0 auto;padding:0 16px 28px}
h2.scr{font:800 21px/1.15 'Archivo',system-ui;letter-spacing:-.01em;margin:18px 0 3px}
.scrsub{font-size:11.5px;color:var(--pn-ink2);margin-bottom:16px}
.sect{font:800 11px/1 'Archivo',system-ui;letter-spacing:.12em;text-transform:uppercase;
  padding-bottom:7px;border-bottom:2px solid var(--pn-rule2);margin:26px 0 0}
p{color:var(--pn-ink2)}

/* header */
header{background:var(--pn-bg);border-bottom:2px solid var(--pn-rule2);
  padding:calc(10px + env(safe-area-inset-top)) 16px 9px}
.hin{max-width:760px;margin:0 auto;display:flex;align-items:center;gap:10px}
.mark{font:800 17px/1 'Archivo',system-ui;letter-spacing:.05em}
.badge{display:inline-flex;align-items:center;gap:8px;margin-left:2px}
.badge i{width:14px;height:14px;flex:none;border:2px solid var(--pn-ink);display:block}
.badge span{font:800 10.5px/1 'Archivo',system-ui;letter-spacing:.1em;text-transform:uppercase}
.hbtns{margin-left:auto;display:flex;gap:0;border:1px solid var(--pn-rule2)}
.hbtn{background:transparent;border:0;border-left:1px solid var(--pn-rule2);color:var(--pn-ink);
  font:800 10.5px/1 'Archivo',system-ui;letter-spacing:.06em;padding:0 9px;height:30px;
  cursor:pointer;display:flex;align-items:center;font-family:inherit}
.hbtn:first-child{border-left:0}
.trustline{max-width:760px;margin:6px auto 0;font-size:11px;color:var(--pn-ink2)}

/* nav */
nav{position:fixed;left:0;right:0;bottom:0;z-index:30;background:var(--pn-bg);
  border-top:2px solid var(--pn-rule2);display:flex;padding-bottom:env(safe-area-inset-bottom)}
nav button{flex:1;min-width:0;background:transparent;border:0;border-top:3px solid transparent;
  color:var(--pn-ink3);font-family:inherit;cursor:pointer;height:56px;
  display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;padding:0 2px}
nav button b{font:800 8.5px/1.1 'Archivo',system-ui;letter-spacing:.05em;text-transform:uppercase;
  max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
nav button[aria-selected="true"]{color:var(--pn-accentText);border-top-color:var(--pn-accent)}
@media(min-width:760px){
  body{padding-bottom:28px}
  nav{position:sticky;top:0;bottom:auto;border-top:0;border-bottom:2px solid var(--pn-rule2);
    max-width:760px;margin:0 auto}
  nav button{flex:0 0 auto;flex-direction:row;gap:7px;height:46px;padding:0 14px;
    border-top:0;border-bottom:3px solid transparent}
  nav button[aria-selected="true"]{border-bottom-color:var(--pn-accent)}
  nav button b{font-size:11px}
}

/* grid cells (never floating cards) */
.grid2{display:grid;grid-template-columns:1fr 1fr;border-left:1px solid var(--pn-rule);
  border-top:1px solid var(--pn-rule)}
.cell{padding:11px 12px;border-right:1px solid var(--pn-rule);border-bottom:1px solid var(--pn-rule)}
.cell .v{font:800 26px/1 'Archivo',system-ui;letter-spacing:-.02em}
.cell .k{margin-top:6px}
.cell .d{font-size:11px;line-height:1.35;color:var(--pn-ink2);margin-top:3px}

.band{background:var(--pn-surface);border:1px solid var(--pn-rule);padding:12px 13px}
.hero{font:800 54px/1 'Archivo',system-ui;letter-spacing:-.03em}
.rule{border-bottom:1px solid var(--pn-rule)}

/* coverage meter */
.mtr{padding:11px 13px;border-bottom:1px solid var(--pn-rule)}
.mtr:last-child{border-bottom:0}
.mtr-h{display:flex;align-items:baseline;gap:8px}
.mtr-h .n{font:800 10px/1 'Archivo',system-ui;color:var(--pn-ink3);width:16px;flex:none}
.mtr-h .l{font-size:12.5px;font-weight:600;flex:1;min-width:0}
.mtr-h .p{font:800 15px/1 'Archivo',system-ui}
.trk{position:relative;height:10px;background:var(--pn-track);margin:7px 0 0 24px}
.trk .f{position:absolute;left:0;top:0;bottom:0;background:var(--pn-ink)}
.trk .prev{position:absolute;top:-3px;bottom:-3px;width:1px;background:var(--pn-ink3)}
.mtr .s{font-size:11px;color:var(--pn-ink2);margin:5px 0 0 24px}

/* nutrient row */
.nrow{padding:13px 14px;border-bottom:1px solid var(--pn-rule);cursor:pointer;
  background:transparent;border-left:0;border-right:0;border-top:0;width:100%;
  text-align:left;font-family:inherit;color:inherit;display:block}
.nrow:last-child{border-bottom:0}
.nrow-h{display:flex;align-items:baseline;gap:8px}
.nrow-h .nm{font-size:13.5px;font-weight:600;flex:1;min-width:0}
.nrow-h .vl{font:800 16px/1 'Archivo',system-ui}
.nrow-h .un{font-size:11px;color:var(--pn-ink2)}
.bar{position:relative;height:13px;background:var(--pn-track);margin-top:9px}
.bar .f{position:absolute;left:0;top:0;bottom:0;background:var(--pn-ink)}
.bar .f.thin{background:var(--pn-hatch),var(--pn-track);border-right:2px solid var(--pn-ink)}
.bar .ref{position:absolute;left:50%;top:-4px;bottom:-4px;width:2px;background:var(--pn-ink);
  transform:translateX(-1px)}
.bar .ref.over{background:var(--pn-bg)}
.bar .clamp{position:absolute;right:2px;top:0;bottom:0;display:flex;align-items:center}
.whisk{position:relative;height:9px;margin-top:3px}
.whisk .ln{position:absolute;top:4px;height:1px;background:var(--pn-ink3)}
.whisk .cap{position:absolute;top:0;bottom:0;width:1px;background:var(--pn-ink3)}
/* The RI label sits on the same 9px row as the whisker, so it knocks the line
   out behind it rather than overprinting it. */
.whisk .rl{position:absolute;left:50%;top:0;transform:translateX(-50%);
  font:800 8px/1 'Archivo',system-ui;letter-spacing:.08em;color:var(--pn-ink2);
  white-space:nowrap;background:var(--pn-bg);padding:0 4px;z-index:1}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.chip{padding:3px 7px;border:1px solid var(--pn-rule2);font-size:10.5px;color:var(--pn-ink2)}
.chip.tex{border:0;background:var(--pn-hatch2),var(--pn-surface2);color:var(--pn-ink);font-weight:600}
.chip.flag{display:inline-flex;align-items:center;gap:5px;border:2px solid var(--pn-accent);
  color:var(--pn-accentText);font-weight:800}
.noref{display:flex;align-items:center;gap:7px;margin-top:8px;padding:6px 8px;
  border:1px dashed var(--pn-rule2)}
.noref span{font-size:11px;line-height:1.35;color:var(--pn-ink2)}
.brk{font-size:11px;color:var(--pn-ink2);margin-top:7px}

/* legend */
.lgd{display:flex;flex-wrap:wrap;gap:12px;padding:9px 0;font-size:10.5px;color:var(--pn-ink2)}
.lgd i{display:inline-block;width:16px;height:9px;margin-right:5px;vertical-align:-1px}

/* pills */
.pills{display:flex;border:1px solid var(--pn-rule2);margin:14px 0 0;overflow-x:auto}
.pills button{flex:1;min-width:60px;background:transparent;border:0;border-left:1px solid var(--pn-rule2);
  font:800 11px/1 'Archivo',system-ui;letter-spacing:.04em;padding:9px 6px;cursor:pointer;
  color:var(--pn-ink2);font-family:inherit;white-space:nowrap}
.pills button:first-child{border-left:0}
.pills button[aria-pressed="true"]{background:var(--pn-ink);color:var(--pn-bg)}

/* state chips row */
.sfil{display:flex;gap:6px;overflow-x:auto;padding:2px 0 10px;-webkit-overflow-scrolling:touch}
.sfil button{flex:none;background:transparent;border:1px solid var(--pn-rule2);color:var(--pn-ink2);
  font:800 10px/1 'Archivo',system-ui;letter-spacing:.04em;text-transform:uppercase;
  padding:7px 9px;cursor:pointer;font-family:inherit;display:flex;align-items:center;gap:6px}
.sfil button[aria-pressed="true"]{background:var(--pn-ink);color:var(--pn-bg);border-color:var(--pn-ink)}
.sfil code{font-size:10px}
.mk{width:11px;height:11px;flex:none;border:1.5px solid var(--pn-ink);display:block}

/* item rows */
.irow{width:100%;text-align:left;background:transparent;border:0;border-bottom:1px solid var(--pn-rule);
  padding:11px 13px;cursor:pointer;font-family:inherit;color:inherit;display:block}
.irow:last-child{border-bottom:0}
.irow-h{display:flex;align-items:baseline;gap:9px}
.irow-h .mk{margin-top:3px}
.irow-h .rw{flex:1;min-width:0;font:600 11.5px/1.35 ui-monospace,Menlo,monospace;
  letter-spacing:.02em;word-break:break-word}
.irow-h .pr{font-size:11.5px;color:var(--pn-ink2);white-space:nowrap}
.irow .meta{font-size:11px;color:var(--pn-ink2);margin:4px 0 0 20px}
.irow .why{font-size:11px;color:var(--pn-ink3);margin:3px 0 0 20px;line-height:1.4}

/* ladder */
.lad{display:flex;align-items:baseline;gap:10px;padding:7px 13px;border-bottom:1px solid var(--pn-rule)}
.lad:last-child{border-bottom:0}
.lad .l{flex:1;min-width:0;font-size:12px}
.lad .v{font:800 13px/1 'Archivo',system-ui}
.lad .nt{font-size:10px;color:var(--pn-ink3);padding:0 13px 8px;word-break:break-word;line-height:1.5}

/* sensitivity */
.srow{padding:10px 13px;border-bottom:1px solid var(--pn-rule)}
.srow:last-child{border-bottom:0}
.srow-h{display:flex;align-items:baseline;gap:8px}
.srow-h .nm{flex:1;min-width:0;font-size:12.5px;font-weight:600}
.srow-h .dl{font:800 12px/1 'Archivo',system-ui;color:var(--pn-accentText)}
.sb{height:7px;margin-top:6px;background:var(--pn-ink)}
.sb.est{background:var(--pn-hatch),var(--pn-surface2);border-right:2px solid var(--pn-ink);margin-top:2px}
.sv{display:flex;gap:10px;font-size:10.5px;color:var(--pn-ink2);margin-top:5px}

/* evidence + reasons */
.ev{font:600 11.5px/1.4 ui-monospace,Menlo,monospace;letter-spacing:.02em;
  border:1px solid var(--pn-rule2);padding:2px 6px;display:inline-block;word-break:break-word}
.rsn{display:flex;gap:10px;padding:9px 13px;border-bottom:1px solid var(--pn-rule)}
.rsn:last-child{border-bottom:0}
.rsn .n{font:800 10px/1.5 'Archivo',system-ui;color:var(--pn-accentText);flex:none}
.rsn p{font-size:11.5px;line-height:1.5}

/* sheet */
.scrim{position:fixed;inset:0;background:var(--pn-scrim);z-index:40;display:flex;
  align-items:flex-end;justify-content:center}
.sheet{background:var(--pn-bg);border-top:2px solid var(--pn-ink);width:100%;max-width:760px;
  max-height:88vh;overflow-y:auto;box-shadow:0 -12px 32px rgba(0,0,0,.28);
  padding-bottom:calc(16px + env(safe-area-inset-bottom))}
.sheet-h{position:sticky;top:0;background:var(--pn-bg);border-bottom:1px solid var(--pn-rule2);
  padding:13px 16px 11px;display:flex;align-items:flex-start;gap:10px}
.sheet-h .tt{flex:1;min-width:0}
.sheet-h h3{font:800 19px/1.1 'Archivo',system-ui;letter-spacing:-.01em}
.xbtn{background:transparent;border:1px solid var(--pn-rule2);color:var(--pn-ink);width:32px;height:32px;
  flex:none;cursor:pointer;font:800 15px/1 'Archivo',system-ui;font-family:inherit}
.sheet-b{padding:14px 16px 18px}

/* buttons */
.btn{display:flex;align-items:center;justify-content:center;gap:8px;width:100%;min-height:48px;
  background:var(--pn-ink);color:var(--pn-bg);border:0;font:800 12px/1 'Archivo',system-ui;
  letter-spacing:.06em;text-transform:uppercase;cursor:pointer;font-family:inherit;padding:0 14px}
.btn.gh{background:transparent;color:var(--pn-ink);border:2px solid var(--pn-ink)}
.btn.acc{background:var(--pn-accent);color:#fff}
.btns{display:flex;flex-direction:column;gap:8px;margin-top:14px}
input[type=search],input[type=text]{width:100%;min-height:44px;background:var(--pn-surface);
  border:1px solid var(--pn-rule2);color:var(--pn-ink);padding:0 12px;font-family:inherit;font-size:12.5px}
input:focus-visible,button:focus-visible,.nrow:focus-visible{outline:2px solid var(--pn-accent);outline-offset:1px}

/* scan */
.view{position:relative;background:var(--pn-ink);aspect-ratio:3/4;overflow:hidden;
  display:flex;align-items:center;justify-content:center}
.view img{width:100%;height:100%;object-fit:contain}
.corner{position:absolute;width:26px;height:26px;border:3px solid var(--pn-bg)}
.shot{width:64px;height:64px;background:var(--pn-bg);border:4px solid var(--pn-ink);cursor:pointer;
  display:block;margin:0 auto}
.stepbar{display:flex;gap:0;border:1px solid var(--pn-rule2);margin-bottom:14px;overflow-x:auto}
.stepbar div{flex:1;min-width:52px;padding:7px 4px;text-align:center;border-left:1px solid var(--pn-rule2);
  font:800 8.5px/1.2 'Archivo',system-ui;letter-spacing:.05em;text-transform:uppercase;color:var(--pn-ink3)}
.stepbar div:first-child{border-left:0}
.stepbar div[data-on="1"]{background:var(--pn-ink);color:var(--pn-bg)}
.ocr{border-bottom:1px solid var(--pn-rule);padding:11px 13px}
.ocr:last-child{border-bottom:0}
.ocr-h{display:flex;align-items:center;gap:8px;margin-bottom:8px}
.ocr-h .ev{flex:1}
.conf{width:34px;height:9px;flex:none;background:var(--pn-track);position:relative}
.conf i{position:absolute;left:0;top:0;bottom:0;background:var(--pn-ink);display:block}
.conf.low i{background:var(--pn-hatch),var(--pn-surface2);border-right:2px solid var(--pn-accent)}
/* "unknown — leave empty" is the whole point of the field, so it must fit:
   the pair stacks until there is room for the placeholder to read in full. */
.ocr-f{display:grid;grid-template-columns:1fr;gap:8px}
@media(min-width:430px){.ocr-f{grid-template-columns:1fr 1fr}}
.fld label{display:block;margin-bottom:3px}
.note{border-left:3px solid var(--pn-accent);background:var(--pn-surface);padding:11px 13px;margin:14px 0}
.note b{display:block;font:800 12px/1.3 'Archivo',system-ui;margin-bottom:4px;color:var(--pn-ink)}
.note p{font-size:11.5px;line-height:1.5}
.empty{padding:22px 13px;text-align:center;color:var(--pn-ink2);font-size:11.5px}
footer{max-width:760px;margin:26px auto 0;padding:12px 16px 0;border-top:1px solid var(--pn-rule);
  font-size:10.5px;color:var(--pn-ink3);line-height:1.6}
[hidden]{display:none!important}
@media(prefers-reduced-motion:no-preference){
  .spin{animation:pnspin 1.1s linear infinite}
}
@keyframes pnspin{to{transform:rotate(360deg)}}
"""

JS = r"""
const D = window.__REPORT__, S = window.__I18N__.S, NAME = window.__I18N__.NAME;
const IDX = {en:0, fr:1, it:2}, LOC = {en:'en-GB', fr:'fr-BE', it:'it-IT'};

let lang = 'en', theme = 'light', screen = 'overview';
let year = 'all', open = null, detail = null, q = '', sf = 'all';
let scan = 'camera', shots = [], mode = 'household';
const SCAN_STEPS = ['camera','preview','processing','review','result'];
try {
  const l = localStorage.getItem('paniere.lang'); if (l && LOC[l]) lang = l;
  const t = localStorage.getItem('paniere.theme'); if (t) theme = t;
} catch (e) { /* private mode */ }
/* ?lang= / ?theme= win over the stored preference — deep links and QA. */
{
  const p = new URLSearchParams(location.search);
  if (LOC[p.get('lang')]) lang = p.get('lang');
  if (p.get('theme') === 'dark' || p.get('theme') === 'light') theme = p.get('theme');
  if (p.get('nut')) { open = p.get('nut'); screen = 'nutrients'; }
  if (SCAN_STEPS.indexOf(p.get('scan')) >= 0) { scan = p.get('scan'); screen = 'scan'; }
}

/* Receipt text is attacker-controllable in principle and is never trusted. */
const esc = s => String(s ?? '').replace(/[&<>"']/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const T = k => (S[k] ? (S[k][IDX[lang]] || S[k][0]) : k);
const n = (v, d) => v == null ? '—'
  : Number(v).toLocaleString(LOC[lang],
      {minimumFractionDigits: d || 0, maximumFractionDigits: d === undefined ? 0 : d});
const pc = (v, d) => n(v, d === undefined ? 1 : d) + '%';
const eur = v => '€' + n(v, 2);
const nutName = k => lang === 'it'
  ? ((D.nutrient_labels && D.nutrient_labels[k]) || k)
  : (NAME[k] ? (lang === 'fr' ? NAME[k][1] : NAME[k][0]) : k);
const arw = s => String(s).replace(/-&gt;|->/g, '→');
/* Source units are USDA-style shout-case (G, MG, UG). Render them as printed. */
const UNITS = {G:'g', MG:'mg', UG:'µg', KCAL:'kcal', KJ:'kJ', IU:'IU'};
const unitOf = k => UNITS[(D.units[k] || '').toUpperCase()] || (D.units[k] || '').toLowerCase();
/* Data-borne prose is localised too — the trust panel must never mix languages. */
const disclaimer = () => (D.disclaimer_i18n && D.disclaimer_i18n[lang]) || D.disclaimer;
const reasons = () => (D.status_reasons_i18n && D.status_reasons_i18n[lang]) || D.status_reasons || [];

const svg = (paths, w) => `<svg width="20" height="20" viewBox="0 0 24 24" fill="none"
  stroke="currentColor" stroke-width="${w || 1.9}" stroke-linecap="square" aria-hidden="true">
  ${paths.map(d => `<path d="${d}"/>`).join('')}</svg>`;

const NAVDEF = [
  ['overview',  'nav.ov', ['M3 4h18v6H3z','M3 14h8v6H3z','M15 14h6v6h-6z']],
  ['nutrients', 'nav.nu', ['M3 6h18','M3 12h13','M3 18h8']],
  ['quality',   'nav.dq', ['M4 3v18','M4 4h14l-2 4 2 4H4']],
  ['purchases', 'nav.pu', ['M4 7h16l-1.4 13H5.4L4 7z','M9 7V4h6v3']],
  ['scan',      'nav.sc', ['M3 8V5h3','M18 5h3v3','M21 16v3h-3','M6 19H3v-3','M7 12h10']]
];

/* Seven states, seven distinct fills — each locked to a word. Only
   `quarantined` is red, because quarantine is a verdict about the DATA. */
const MARK = {
  usable: 'background:var(--pn-ink)',
  quantity_unknown: 'background:var(--pn-hatch2),var(--pn-surface2)',
  volume_no_density: 'background:linear-gradient(90deg,var(--pn-ink) 0 50%,transparent 50%)',
  not_food_or_unmatched: 'background:transparent',
  quarantined: 'background:var(--pn-accent);border-color:var(--pn-accent)',
  no_food_record: 'background:linear-gradient(0deg,var(--pn-ink) 0 50%,transparent 50%)',
  receipt_metadata: 'background:var(--pn-ink3)'
};
const STATE_ORDER = ['usable','quantity_unknown','volume_no_density',
  'not_food_or_unmatched','quarantined','no_food_record','receipt_metadata'];

const trustKey = () => D.status === 'Beta' ? 'beta' : D.status === 'Validated' ? 'validated' : 'draft';
const trustFill = () => D.status === 'Validated' ? 'background:var(--pn-ink)'
  : D.status === 'Beta' ? 'background:linear-gradient(90deg,var(--pn-ink) 0 50%,transparent 50%)'
  : 'background:var(--pn-hatch2),var(--pn-surface2)';

/* ── Overview ───────────────────────────────────────────────────────────── */
function vOverview() {
  const c = D.coverage, r = D.receipts;
  const chain = [
    [T('ov.c1'), c.pct_matched, n(c.rows_food_matched)+' / '+n(c.rows_product_lines), 100],
    [T('ov.c2'), c.pct_quantity_of_matched, n(c.rows_usable)+' / '+n(c.rows_food_matched), c.pct_matched],
    [T('ov.c3'), c.pct_usable_of_all,
      n(c.rows_usable)+' / '+n(c.rows_product_lines)+' → '+pc(c.pct_usable_of_all_with_estimates)+' '
      + (lang==='fr'?'avec estimations':lang==='it'?'con stime':'with estimates'), c.pct_quantity_of_matched],
    [T('ov.c4'), c.pct_spend_covered, eur(c.spend_usable_eur)+' / '+eur(c.spend_total_eur), c.pct_usable_of_all]
  ];
  const tiles = [
    [n(r.receipts_in_analysis), T('ov.t1'), T('ov.t1d')],
    [n(r.images_unique), T('ov.t2'), T('ov.t2d')],
    [n(r.images_without_ocr.length), T('ov.t3'), T('ov.t3d')],
    [n(r.duplicate_pairs), T('ov.t4'), T('ov.t4d')]
  ];
  return `
  <div class="note"><b>${esc(T('ov.measures'))}</b><p>${esc(disclaimer())}</p></div>

  <div class="band" style="padding:16px 14px 14px">
    <div class="hero tab">${pc(c.pct_usable_of_all)}</div>
    <div style="font-size:13px;font-weight:600;margin-top:5px">${esc(T('ov.usableHead'))}</div>
    <div class="mono tab" style="font-size:11px;color:var(--pn-ink2);margin-top:6px">
      ${n(c.rows_usable)} / ${n(c.rows_product_lines)} · ${eur(c.spend_usable_eur)} / ${eur(c.spend_total_eur)}</div>
    <p style="font-size:11.5px;margin-top:9px">${esc(T('ov.notAScore'))}</p>
  </div>

  <div class="sect">${esc(T('ov.chain'))}</div>
  <div style="border:1px solid var(--pn-rule);border-top:0">
    ${chain.map((x, i) => `
      <div class="mtr">
        <div class="mtr-h"><span class="n tab">${String(i+1).padStart(2,'0')}</span>
          <span class="l">${esc(x[0])}</span><span class="p tab">${pc(x[1])}</span></div>
        <div class="trk"><div class="f" style="width:${Math.min(100,x[1])}%"></div>
          ${x[3] < 100 ? `<div class="prev" style="left:${Math.min(100,x[3])}%"></div>` : ''}</div>
        <div class="s tab">${esc(x[2])}</div>
      </div>`).join('')}
  </div>

  <div class="sect">${esc(T('ov.receipts'))}</div>
  <div class="grid2">
    ${tiles.map(t => `<div class="cell"><div class="v tab">${t[0]}</div>
      <div class="k micro">${esc(t[1])}</div><div class="d">${esc(t[2])}</div></div>`).join('')}
  </div>

  <div class="sect">${esc(T('ov.period'))}</div>
  <div class="band mono tab" style="border-top:0">${esc(r.date_first)} → ${esc(r.date_last)}</div>

  <div class="sect">${esc(T('ov.why'))}</div>
  <div style="border:1px solid var(--pn-rule);border-top:0">
    ${reasons().map((x,i) => `<div class="rsn"><span class="n tab">${String(i+1).padStart(2,'0')}</span>
      <p>${esc(x)}</p></div>`).join('')}
  </div>
  <p style="font-size:11px;margin-top:10px">${esc(T('ov.draftFoot'))}</p>`;
}

/* ── Nutrients ──────────────────────────────────────────────────────────── */
function nutSource() { return year === 'all' ? D.nutrients : (D.nutrients_by_year[year] || null); }

function vNutrients() {
  const src = nutSource();
  const sens = {};
  (D.sensitivity_estimated_quantities || []).forEach(s => { sens[s.nutrient] = s; });
  const yl = ['all'].concat(D.years);

  const pills = `<div class="pills">${yl.map(y => `
    <button data-year="${esc(y)}" aria-pressed="${year === y}">
      ${y === 'all' ? esc(T('nu.all')) : esc(y)}</button>`).join('')}</div>`;

  if (!src) return `<h2 class="scr">${esc(T('nu.title'))}</h2>
    <div class="scrsub">${esc(T('nu.per'))}</div>${pills}
    <div class="band" style="margin-top:14px"><b style="font:800 14px/1.2 'Archivo',system-ui">
      ${esc(T('nu.noYearTitle'))}</b><p style="margin-top:6px">${esc(T('nu.noYearBody'))}</p>
      <div class="btns"><button class="btn gh" data-allyears>${esc(T('nu.showAll'))}</button></div></div>`;

  const rows = D.nutrient_order.filter(k => src[k]).map(k => {
    const d = src[k], unit = unitOf(k);
    const hasRef = d.reference != null, max = hasRef ? d.reference * 2 : 0;
    const w = hasRef ? Math.min(100, d.value / max * 100) : 0;
    const thin = hasRef && d.coverage_pct < 80;
    const clamped = hasRef && d.value > max;
    const se = year === 'all' ? sens[k] : null;
    const brk = !!(se && hasRef && Math.abs(se.delta_pct) >= 5);
    const b1 = brk ? Math.min(100, Math.min(se.observed_only, se.with_estimates)/max*100) : 0;
    const b2 = brk ? Math.min(100, Math.max(se.observed_only, se.with_estimates)/max*100) : 0;
    const dec = d.value < 10 ? 2 : 1;
    const fragile = d.top_item_share_pct >= 25 || d.dominated_by_single_item === true;

    return `<button class="nrow" data-nut="${esc(k)}">
      <div class="nrow-h"><span class="nm">${esc(nutName(k))}</span>
        <span class="vl tab">${n(d.value, dec)}</span><span class="un">${esc(unit)}</span></div>
      ${hasRef ? `
      <div class="bar">
        <div class="f${thin ? ' thin' : ''}" style="width:${w}%"></div>
        <div class="ref${clamped ? ' over' : ''}"></div>
        ${clamped ? `<span class="clamp">${svg(['m9 6 6 6-6 6'], 4)}</span>` : ''}
      </div>
      <div class="whisk">
        ${brk ? `<div class="ln" style="left:${b1}%;width:${b2-b1}%"></div>
          <div class="cap" style="left:${b1}%"></div><div class="cap" style="left:${b2}%"></div>` : ''}
        <span class="rl">RI ${n(d.reference, d.reference < 10 ? 2 : 0)} ${esc(unit)}</span>
      </div>` : `
      <div class="noref">${svg(['M4 12h16','M4 6h16','M4 18h7'], 2.2)}
        <span>${esc(T('nu.noRef'))}</span></div>`}
      <div class="chips">
        <span class="chip tab">${pc(d.coverage_pct)} ${esc(T('nu.cov'))}</span>
        ${thin ? `<span class="chip tex">${esc(T('nu.thinChip'))}</span>` : ''}
        ${fragile ? `<span class="chip flag">${svg(['M12 9v5','M12 17h.01','M3 20 12 4l9 16Z'], 2.5)}
          ${esc(T('nu.fragile'))}</span>` : ''}
      </div>
      ${brk ? `<div class="brk tab">${esc(T('nu.bracketText'))} ${n(se.with_estimates, dec)} ${esc(unit)}
        (${se.delta_pct > 0 ? '+' : ''}${n(se.delta_pct, 1)}%)</div>` : ''}
    </button>`;
  }).join('');

  return `<h2 class="scr">${esc(T('nu.title'))}</h2>
    <div class="scrsub">${esc(T('nu.per'))}</div>
    ${pills}
    <div class="lgd">
      <span><i style="background:var(--pn-ink)"></i>${esc(T('nu.obs'))}</span>
      <span><i style="background:var(--pn-hatch),var(--pn-track)"></i>${esc(T('nu.thin'))}</span>
      <span><i style="background:transparent;border-left:1px solid var(--pn-ink3);
        border-right:1px solid var(--pn-ink3);position:relative">
        <b style="position:absolute;top:4px;left:0;right:0;height:1px;background:var(--pn-ink3);display:block"></b>
        </i>${esc(T('nu.bracket'))}</span>
      <span><i style="width:2px;background:var(--pn-ink)"></i>${esc(T('nu.refMark'))}</span>
    </div>
    <div style="border:1px solid var(--pn-rule)">${rows}</div>
    <p style="font-size:11px;margin-top:10px">${esc(T('nu.axisNote'))}</p>`;
}

/* ── Data quality ───────────────────────────────────────────────────────── */
function vQuality() {
  const r = D.receipts, c = D.coverage;
  const inA = r.receipts_in_analysis, uniq = r.images_unique;
  const notIn = uniq - inA, never = r.images_without_ocr.length, empt = r.ocr_empty.length;
  const L = (k, v, pad, weight, note) => `
    <div class="lad"><span class="l" style="padding-left:${pad}px;font-weight:${weight}">${esc(T(k))}</span>
      <span class="v tab">${v}</span></div>
    ${note ? `<div class="nt mono">${esc(note)}</div>` : ''}`;

  const ladder = [
    L('dq.l1', n(r.images_total), 0, 700),
    L('dq.l2', '−' + n(r.duplicate_pairs), 16, 400),
    L('dq.l3', n(uniq), 0, 700),
    L('dq.l4', n(r.ocr_csv_files), 16, 400),
    L('dq.l5', n(empt), 30, 400, r.ocr_empty.join('   ')),
    L('dq.l6', n(inA), 0, 800),
    L('dq.l7', n(notIn), 0, 700),
    L('dq.l8', n(never), 16, 400, r.images_without_ocr.join('   ')),
    L('dq.l9', n(empt), 16, 400),
    L('dq.l10', n(notIn - never - empt), 16, 400, T('dq.l10n'))
  ].join('');

  const sens = (D.sensitivity_estimated_quantities || []).slice()
    .sort((a, b) => Math.abs(b.delta_pct) - Math.abs(a.delta_pct)).map(s => {
      const unit = unitOf(s.nutrient);
      const mx = Math.max(s.observed_only, s.with_estimates) || 1;
      const dec = mx < 10 ? 2 : mx < 200 ? 1 : 0;
      return `<div class="srow">
        <div class="srow-h"><span class="nm">${esc(nutName(s.nutrient))}</span>
          <span class="dl tab">${s.delta_pct > 0 ? '↑ +' : '↓ −'}${n(Math.abs(s.delta_pct),1)}%</span></div>
        <div class="sb" style="width:${s.observed_only/mx*100}%"></div>
        <div class="sb est" style="width:${s.with_estimates/mx*100}%"></div>
        <div class="sv tab"><span>${n(s.observed_only,dec)} ${esc(unit)}</span>
          <span>${n(s.with_estimates,dec)} ${esc(unit)}</span></div>
      </div>`;
    }).join('');

  const quar = D.quarantined.map(x => `
    <div class="ocr"><div class="ocr-h"><code class="ev">${esc(x.product_name)}</code></div>
      <div class="tab" style="font-size:11px;color:var(--pn-ink2)">${n(x.rows)} ${esc(T('dq.rowsWord'))} · ${eur(x.spend)}</div>
      <p style="font-size:11.5px;margin-top:5px">${esc(x.reason)}</p></div>`).join('');

  const review = D.needs_review.length ? D.needs_review.map(x => `
    <div class="lad"><span class="l mono" style="font-size:11px">${esc(arw(x.mapping))}</span>
      <span class="v tab">${n(x.rows)}</span></div>`).join('')
    : `<div class="empty">—</div>`;

  const unres = D.unresolved.slice(0, 40).map(x => `
    <div class="irow" style="cursor:default">
      <div class="irow-h"><span class="mk" style="${MARK[x.state] || ''}"></span>
        <code class="rw">${esc(x.product_name)}</code>
        <span class="pr tab">${eur(x.spend)}</span></div>
      <div class="meta tab">${n(x.rows)} ${esc(T('dq.rowsWord'))} · ${esc(T('st.' + x.state))}</div></div>`).join('');

  return `<h2 class="scr">${esc(T('dq.title'))}</h2>
    <div class="scrsub">${esc(T('dq.sub'))}</div>

    <div class="sect">${esc(T('dq.ladder'))}</div>
    <div style="border:1px solid var(--pn-rule);border-top:0">${ladder}</div>

    <div class="sect">${esc(T('dq.sens'))}</div>
    <p style="font-size:11px;margin:9px 0">${esc(T('dq.sensNote'))}</p>
    <div class="lgd" style="padding-top:0">
      <span><i style="background:var(--pn-ink)"></i>${esc(T('dq.obs'))}</span>
      <span><i style="background:var(--pn-hatch),var(--pn-surface2)"></i>${esc(T('dq.est'))}</span>
    </div>
    <div style="border:1px solid var(--pn-rule)">${sens}</div>

    <div class="sect">${esc(T('dq.quar'))}</div>
    <p style="font-size:11px;margin:9px 0">${esc(T('dq.quarNote'))}</p>
    <div style="border:1px solid var(--pn-rule)">${quar}</div>

    <div class="sect">${esc(T('dq.review'))}</div>
    <p style="font-size:11px;margin:9px 0">${esc(T('dq.reviewNote'))}</p>
    <div style="border:1px solid var(--pn-rule)">${review}</div>

    <div class="sect">${esc(T('dq.unres'))}</div>
    <p style="font-size:11px;margin:9px 0">${esc(T('dq.unresNote'))}</p>
    <div style="border:1px solid var(--pn-rule)">${unres}</div>`;
}

/* ── Purchases ──────────────────────────────────────────────────────────── */
function vPurchases() {
  const c = D.coverage, r = D.receipts, bs = c.by_state;
  const total = c.rows_total_raw - c.rows_dropped_as_duplicate;
  const chips = [{k:'all', l:T('st.all'), n:total}]
    .concat(STATE_ORDER.map(k => ({k, l:T('st.'+k), n:bs[k] || 0})))
    .map(x => `<button data-sf="${esc(x.k)}" aria-pressed="${sf === x.k}">
        ${x.k === 'all' ? '' : `<span class="mk" style="${MARK[x.k] || ''}"></span>`}
        ${esc(x.l)} <code class="tab">${n(x.n)}</code></button>`).join('');

  const qq = q.trim().toLowerCase();
  const items = D.items.filter(i =>
    (sf === 'all' || i.state === sf) &&
    (!qq || i.product_name.toLowerCase().indexOf(qq) >= 0 || (i.food||'').toLowerCase().indexOf(qq) >= 0));

  const qtyOf = i => i.qty_amount != null ? n(i.qty_amount) + ' ' + i.qty_unit
    : i.declared_g != null ? n(i.declared_g) + ' g · ' + T('pu.estimated')
    : T('pu.unknown');

  const rows = items.slice(0, 300).map((i, ix) => `
    <button class="irow" data-item="${D.items.indexOf(i)}">
      <div class="irow-h"><span class="mk" style="${MARK[i.state] || ''}"></span>
        <code class="rw">${esc(i.product_name)}</code>
        <span class="pr tab">${i.price != null ? eur(i.price) : '—'}</span></div>
      <div class="meta tab">${i.food ? esc(i.food) : '<i>'+esc(T('pu.noFood'))+'</i>'} · ${esc(qtyOf(i))}</div>
      <div class="why">${esc((i.issues && i.issues.length) ? T('is.'+i.issues[0])
        : (i.state === 'usable' ? T('pd.whyUsable') : T('pd.whyNot')))}</div>
    </button>`).join('');

  return `<h2 class="scr">${esc(T('pu.title'))}</h2>
    <div class="scrsub tab">${n(total)} ${esc(T('dq.rowsWord'))} · ${eur(c.spend_total_eur)} · ${esc(r.date_first)} → ${esc(r.date_last)}</div>
    <input type="search" id="q" placeholder="${esc(T('pu.searchPh'))}" value="${esc(q)}"
      autocomplete="off" autocapitalize="off" spellcheck="false">
    <div class="sfil" style="margin-top:10px">${chips}</div>
    ${items.length ? `<div style="border:1px solid var(--pn-rule)">${rows}</div>
      ${items.length > 300 ? `<p style="font-size:11px;margin-top:9px" class="tab">${n(items.length)} → 300</p>` : ''}`
      : `<div class="band"><b style="font:800 14px/1.2 'Archivo',system-ui">${esc(T('pu.noResults'))}</b>
         <p style="margin-top:6px">${esc(T('pu.noResultsBody'))}</p>
         <div class="btns"><button class="btn gh" data-clear>${esc(T('pu.clear'))}</button></div></div>`}`;
}

/* ── Scan ───────────────────────────────────────────────────────────────── */

function vScan() {
  const bar = `<div class="stepbar">${SCAN_STEPS.map((s,i) => `
    <div data-on="${SCAN_STEPS.indexOf(scan) >= i ? 1 : 0}">${esc(T('sc.'+(
      s==='camera'?'camera':s==='preview'?'preview':s==='processing'?'processing':
      s==='review'?'review':'result')))}</div>`).join('')}</div>`;

  if (scan === 'camera') return `<h2 class="scr">${esc(T('sc.guide'))}</h2>
    <div class="scrsub">${esc(T('sc.camHint'))}</div>${bar}
    <div class="view">
      <div class="corner" style="top:14px;left:14px;border-right:0;border-bottom:0"></div>
      <div class="corner" style="top:14px;right:14px;border-left:0;border-bottom:0"></div>
      <div class="corner" style="bottom:14px;left:14px;border-right:0;border-top:0"></div>
      <div class="corner" style="bottom:14px;right:14px;border-left:0;border-top:0"></div>
      <span class="micro" style="color:var(--pn-bg)">${esc(T('sc.guide'))}</span>
    </div>
    <div style="padding:18px 0"><label class="shot" for="cam" aria-label="${esc(T('sc.camera'))}"></label>
      <input id="cam" type="file" accept="image/*" capture="environment" multiple hidden></div>
    ${shots.length ? `<p class="tab" style="font-size:11px;text-align:center">${n(shots.length)} ${esc(T('sc.frames'))}</p>` : ''}`;

  if (scan === 'preview') return `<h2 class="scr">${esc(T('sc.previewTitle'))}</h2>
    <div class="scrsub">${esc(T('sc.previewBody'))}</div>${bar}
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
      ${shots.map((s,i) => `<div><div class="view" style="aspect-ratio:2/3"><img src="${s}" alt=""></div>
        <div class="micro" style="margin-top:5px">${esc(T(i===0?'sc.frame1':'sc.frame2'))}</div></div>`).join('')}
    </div>
    <div class="btns">
      <button class="btn" data-scan="processing">${esc(T('sc.accept'))}</button>
      <label class="btn gh" for="cam2">${esc(T('sc.addFrame'))}</label>
      <input id="cam2" type="file" accept="image/*" capture="environment" multiple hidden>
      <button class="btn gh" data-retake>${esc(T('sc.retake'))}</button>
    </div>`;

  if (scan === 'processing') return `<h2 class="scr">${esc(T('sc.procTitle'))}</h2>${bar}
    <div class="note"><b>${esc(T('sc.queueTitle'))}</b><p>${esc(T('sc.queueBody'))}</p></div>
    <div style="border:1px solid var(--pn-rule)">
      ${[['sc.p1',1],['sc.p2',0],['sc.p3',0],['sc.p4',0]].map(x => `
        <div class="lad"><span class="l">${esc(T(x[0]))}</span>
          <span class="v">${x[1] ? '✓' : '·'}</span></div>`).join('')}
    </div>
    <p style="font-size:11px;margin-top:10px">${esc(T('sc.procNote'))}</p>
    <div class="btns"><button class="btn" data-scan="review">${esc(T('sc.skip'))}</button>
      <button class="btn gh" data-retake>${esc(T('sc.cancel'))}</button></div>`;

  if (scan === 'review') return `<h2 class="scr">${esc(T('sc.reviewTitle'))}</h2>
    <div class="scrsub">${esc(T('sc.summary'))}</div>${bar}
    <div style="border:1px solid var(--pn-rule)">
      ${OCR.map((l, i) => `<div class="ocr">
        <div class="ocr-h"><code class="ev">${esc(l.raw)}</code>
          <span class="conf${l.conf < .7 ? ' low' : ''}" title="${esc(T(l.conf>=.9?'sc.confHigh':l.conf>=.7?'sc.confMid':'sc.confLow'))}">
            <i style="width:${Math.round(l.conf*100)}%"></i></span></div>
        <div class="ocr-f">
          <div class="fld"><label class="micro">${esc(T('sc.qty'))}</label>
            <input type="text" data-ocr="${i}" data-k="qty" value="${esc(l.qty)}"
              placeholder="${esc(T('sc.unknownPh'))}"></div>
          <div class="fld"><label class="micro">${esc(T('sc.price'))}</label>
            <input type="text" data-ocr="${i}" data-k="price" value="${esc(l.price)}"></div>
        </div></div>`).join('')}
    </div>
    <p style="font-size:11px;margin-top:10px">${esc(T('sc.reviewFoot'))}</p>
    <div class="btns"><button class="btn" data-scan="result">${esc(T('sc.save'))}</button></div>`;

  return `<h2 class="scr">${esc(T('sc.resultTitle'))}</h2>${bar}
    <div class="grid2">
      <div class="cell"><div class="v tab">2</div><div class="k micro">${esc(T('sc.countedTile'))}</div></div>
      <div class="cell"><div class="v tab">5</div><div class="k micro">${esc(T('sc.needReview'))}</div></div>
    </div>
    <div class="sect">${esc(T('sc.covEffect'))}</div>
    <div class="band" style="border-top:0"><div class="hero tab" style="font-size:34px">${esc(T('sc.covDelta'))}</div>
      <p style="margin-top:8px">${esc(T('sc.covNote'))}</p></div>
    <div class="btns"><button class="btn" data-retake>${esc(T('sc.scanAnother'))}</button>
      <button class="btn gh" data-goto="overview">${esc(T('sc.backToReport'))}</button></div>`;
}

/* Demo lines for the correction step. There is no OCR backend in this build,
   so these stand in for a real read — the flow is real, the text is not. */
let OCR = [
  {raw:'PAIN DE VIANDE', qty:'', price:'11,52', conf:.96},
  {raw:'HET TRAAGSTE BROOD P', qty:'', price:'4,57', conf:.71},
  {raw:'AVOCAT', qty:'', price:'2,78', conf:.93},
  {raw:'ROSTIER PURE DORC', qty:'', price:'6,85', conf:.44},
  {raw:'185G LAYS PAPRIKA', qty:'185 g', price:'2,99', conf:.98},
  {raw:'6X33CL SCH GINGER', qty:'198 cl', price:'6,59', conf:.88},
  {raw:'40G DLL PATE NOI', qty:'40 g', price:'2,55', conf:.62}
];

/* ── Sheets ─────────────────────────────────────────────────────────────── */
function sheet() {
  if (open) {
    const src = nutSource(); if (!src || !src[open]) return '';
    const d = src[open], unit = unitOf(open);
    const dec = d.value < 10 ? 2 : 1;
    const mx = Math.max.apply(null, d.top_contributors.map(x => x.share_pct)) || 1;
    return shell(T('nu.contrib'), nutName(open), `
      <div style="display:flex;align-items:baseline;gap:8px">
        <span class="hero tab" style="font-size:34px">${n(d.value, dec)}</span>
        <span style="font-size:12px;color:var(--pn-ink2)">${esc(unit)}</span></div>
      <div class="tab" style="font-size:11px;color:var(--pn-ink2);margin-top:6px">${pc(d.coverage_pct)} ${esc(T('nu.cov'))}</div>
      <p style="font-size:11.5px;margin-top:8px">${esc(d.reference == null ? T('nu.noRef')
        : T('nu.refLine') + ' ' + n(d.reference, d.reference < 10 ? 2 : 0) + ' ' + unit
          + ' · ' + d.reference_kind + ' · ' + pc(d.pct_of_reference))}</p>
      <div class="sect">${esc(T('nu.contrib'))}</div>
      <div style="border:1px solid var(--pn-rule);border-top:0">
        ${d.top_contributors.map(x => `<div class="ocr">
          <div class="ocr-h"><code class="ev">${esc(x.product_name)}</code>
            <span class="tab" style="font-size:11px;font-weight:800">${pc(x.share_pct)}</span></div>
          <div class="sb" style="width:${x.share_pct/mx*100}%"></div>
          <div class="tab" style="font-size:11px;color:var(--pn-ink2);margin-top:5px">
            → ${esc(x.food)} · ${esc(x.date)} · ${n(x.amount,1)} ${esc(unit)}</div></div>`).join('')}
      </div>
      <p style="font-size:11px;margin-top:10px">${esc(T('nu.evidence'))}</p>`);
  }
  if (detail != null) {
    const i = D.items[detail]; if (!i) return '';
    const row = (k, v) => `<div class="lad"><span class="l">${esc(T(k))}</span>
      <span class="v tab" style="font-size:12px;font-weight:600;text-align:right">${v}</span></div>`;
    return shell(T('pd.asPrinted'), i.product_name, `
      <code class="ev" style="font-size:13px">${esc(i.product_name)}</code>
      <div style="border:1px solid var(--pn-rule);margin-top:14px">
        ${row('pd.food', i.food ? esc(i.food) : '—')}
        ${row('pd.qty', i.qty_amount != null ? n(i.qty_amount) + ' ' + esc(i.qty_unit) : esc(T('pu.unknown')))}
        ${row('pd.method', esc(T('qm.' + (i.qty_method === 'not_on_label' ? 'not_on_label' : i.qty_method))))}
        ${i.declared_g != null ? row('pd.declared', n(i.declared_g) + ' g') : ''}
        ${row('pd.price', i.price != null ? eur(i.price) : '—')}
        ${row('pd.date', esc(i.date))}
        ${row('pd.energy', i.energy != null ? n(i.energy) + ' kcal' : '—')}
        ${row('pd.record', esc(T('pd.recordVal')))}
      </div>
      <div class="sect">${esc(T('pd.whyCounted'))}</div>
      <div style="border:1px solid var(--pn-rule);border-top:0;padding:11px 13px">
        <div style="display:flex;align-items:center;gap:9px;margin-bottom:7px">
          <span class="mk" style="${MARK[i.state] || ''}"></span>
          <span class="micro" style="color:var(--pn-ink)">${esc(T('st.' + i.state))}</span></div>
        <p style="font-size:11.5px">${esc(i.state === 'usable' ? T('pd.whyUsable') : T('pd.whyNot'))}</p>
        ${(i.issues || []).map(x => S['is.' + x] ? `<p style="font-size:11.5px;margin-top:7px">${esc(T('is.'+x))}</p>` : '').join('')}
      </div>
      <div class="sect">${esc(T('pd.confidence'))}</div>
      <p style="font-size:11.5px;margin-top:9px">${esc(T('pd.confidenceBody'))}</p>`);
  }
  return '';
}
function shell(kicker, title, body) {
  return `<div class="scrim" data-scrim><div class="sheet" role="dialog" aria-modal="true">
    <div class="sheet-h"><div class="tt"><div class="micro">${esc(kicker)}</div>
      <h3>${esc(title)}</h3></div>
      <button class="xbtn" data-close aria-label="Close">✕</button></div>
    <div class="sheet-b">${body}</div></div></div>`;
}

/* ── Render ─────────────────────────────────────────────────────────────── */
const VIEWS = {overview:vOverview, nutrients:vNutrients, quality:vQuality,
               purchases:vPurchases, scan:vScan};

function render() {
  document.documentElement.setAttribute('data-t', theme);
  document.documentElement.lang = lang;

  document.getElementById('trustw').innerHTML =
    `<i style="${trustFill()}"></i><span>${esc(T('trust.' + trustKey()))}</span>`;
  document.getElementById('trustline').textContent = T('trust.' + trustKey() + '.d');
  document.getElementById('langb').textContent = lang.toUpperCase();

  document.getElementById('nav').innerHTML = NAVDEF.map(d => `
    <button data-tab="${d[0]}" role="tab" aria-selected="${screen === d[0]}">
      ${svg(d[2], screen === d[0] ? 2.3 : 1.9)}<b>${esc(T(d[1]))}</b></button>`).join('');

  document.getElementById('main').innerHTML = VIEWS[screen]();
  document.getElementById('sheet').innerHTML = sheet();
  document.body.style.overflow = (open || detail != null) ? 'hidden' : '';
  wire();
}

function wire() {
  const m = document.getElementById('main');
  m.querySelectorAll('[data-year]').forEach(b => b.onclick = () => { year = b.dataset.year; open = null; render(); });
  m.querySelectorAll('[data-nut]').forEach(b => b.onclick = () => { open = b.dataset.nut; render(); });
  m.querySelectorAll('[data-item]').forEach(b => b.onclick = () => { detail = +b.dataset.item; render(); });
  m.querySelectorAll('[data-sf]').forEach(b => b.onclick = () => { sf = b.dataset.sf; render(); });
  m.querySelectorAll('[data-scan]').forEach(b => b.onclick = () => { scan = b.dataset.scan; render(); });
  m.querySelectorAll('[data-goto]').forEach(b => b.onclick = () => { screen = b.dataset.goto; render(); });
  const ay = m.querySelector('[data-allyears]'); if (ay) ay.onclick = () => { year = 'all'; render(); };
  const cl = m.querySelector('[data-clear]'); if (cl) cl.onclick = () => { q = ''; sf = 'all'; render(); };
  const rt = m.querySelector('[data-retake]');
  if (rt) rt.onclick = () => { shots.forEach(URL.revokeObjectURL); shots = []; scan = 'camera'; render(); };

  m.querySelectorAll('input[type=file]').forEach(inp => inp.onchange = e => {
    const files = Array.from(e.target.files || []);
    if (!files.length) return;
    shots = shots.concat(files.slice(0, 4).map(f => URL.createObjectURL(f)));
    scan = 'preview'; render();
  });
  m.querySelectorAll('[data-ocr]').forEach(inp => inp.oninput = e => {
    OCR[+inp.dataset.ocr][inp.dataset.k] = e.target.value;
  });

  const qi = document.getElementById('q');
  if (qi) qi.oninput = e => {
    q = e.target.value; const pos = e.target.selectionStart; render();
    const nq = document.getElementById('q'); nq.focus(); nq.setSelectionRange(pos, pos);
  };

  const sh = document.getElementById('sheet');
  sh.querySelectorAll('[data-close]').forEach(b => b.onclick = close);
  const sc = sh.querySelector('[data-scrim]');
  if (sc) sc.onclick = e => { if (e.target === sc) close(); };
}
function close() { open = null; detail = null; render(); }

document.getElementById('nav').onclick = e => {
  const b = e.target.closest('[data-tab]'); if (!b) return;
  screen = b.dataset.tab; open = null; detail = null;
  history.replaceState(null, '', '#' + screen);
  render(); window.scrollTo(0, 0);
};
document.getElementById('themeb').onclick = () => {
  theme = theme === 'dark' ? 'light' : 'dark';
  try { localStorage.setItem('paniere.theme', theme); } catch (e) {}
  render();
};
document.getElementById('langb').onclick = () => {
  lang = lang === 'en' ? 'fr' : lang === 'fr' ? 'it' : 'en';
  try { localStorage.setItem('paniere.lang', lang); } catch (e) {}
  render();
};
addEventListener('keydown', e => { if (e.key === 'Escape' && (open || detail != null)) close(); });
addEventListener('hashchange', () => {
  const h = (location.hash || '').replace('#', '');
  if (VIEWS[h] && h !== screen) { screen = h; render(); }
});

const h0 = (location.hash || '').replace('#', '');
if (VIEWS[h0]) screen = h0;
render();
if ('serviceWorker' in navigator && location.protocol.startsWith('http')) {
  navigator.serviceWorker.register('./sw.js').catch(() => {});
}
"""


def build() -> None:
    data = json.loads(REPORT_JSON.read_text(encoding="utf-8"))
    i18n = json.loads(I18N_JSON.read_text(encoding="utf-8"))

    def island(obj: object) -> str:
        return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")

    html = f"""<!DOCTYPE html>
<html lang="en" data-t="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta http-equiv="Content-Security-Policy"
      content="default-src 'none'; script-src 'self' 'unsafe-inline'; worker-src 'self'; \
style-src 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; manifest-src 'self'; \
base-uri 'none'; form-action 'none'">
<title>Paniere — Delhaize basket</title>
<link rel="manifest" href="./manifest.webmanifest">
<meta name="theme-color" content="#ec3013">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<style>{CSS}</style>
</head>
<body>
<header><div class="hin">
  <span class="mark">PANIERE</span>
  <span class="badge" id="trustw"></span>
  <span class="hbtns">
    <button class="hbtn" id="langb" aria-label="Language">EN</button>
    <button class="hbtn" id="themeb" aria-label="Theme">◐</button>
  </span>
</div><div class="trustline" id="trustline"></div></header>

<nav id="nav" role="tablist"></nav>

<div class="wrap"><main id="main"></main>
<footer>
  {data['receipts']['receipts_in_analysis']} receipts · normalised to {data['kcal_normalisation']} kcal ·
  EU Reg. 1169/2011 Annex XIII rescaled · per-100&nbsp;g values still from the legacy pyfooda
  snapshot, not yet CIQUAL / FoodData Central.
</footer></div>

<div id="sheet"></div>

<script>window.__I18N__={island(i18n)};</script>
<script>window.__REPORT__={island(data)};</script>
<script>{JS}</script>
</body>
</html>
"""
    PUBLIC.mkdir(exist_ok=True)
    (PUBLIC / "index.html").write_text(html, encoding="utf-8")
    (PUBLIC / "manifest.webmanifest").write_text(
        json.dumps(MANIFEST, ensure_ascii=False, indent=1), encoding="utf-8")
    (PUBLIC / "sw.js").write_text(SERVICE_WORKER, encoding="utf-8")

    kb = (PUBLIC / "index.html").stat().st_size / 1024
    print(f"public/index.html            {kb:,.0f} KB   status={data['status']}")
    print(f"  strings                    {len(i18n['S'])} × EN/FR/IT")
    print(f"  screens                    overview · nutrients · quality · purchases · scan")
    print(f"public/manifest.webmanifest  ok")
    print(f"public/sw.js                 ok")


if __name__ == "__main__":
    build()
