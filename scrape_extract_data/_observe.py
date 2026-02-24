"""
_observe.py — embedded observe mode for scraper self-recovery
=============================================================
Activated automatically when a scraper detects it is stuck:
  - N consecutive failures (e.g. image not found for Delhaize)
  - 0 items found after a full page load (Carrefour / Colruyt)

Records the user's browser actions (clicks, navigations, network) to a JSON
session file so the scraper logic can be quickly rebuilt for a changed website.
"""
from __future__ import annotations
import json
import time
from datetime import datetime
from pathlib import Path

SESSION_DIR = Path(__file__).parent / "sessions"
SESSION_DIR.mkdir(exist_ok=True)

# Minimal JS injected to capture clicks + generate the best CSS selector
_CLICK_JS = """
(() => {
  if (window.__observeInjected) return;
  window.__observeInjected = true;

  function bestSel(el) {
    if (el.dataset && el.dataset.testid) return `[data-testid="${el.dataset.testid}"]`;
    if (el.getAttribute('aria-label'))   return `[aria-label="${el.getAttribute('aria-label')}"]`;
    if (el.id) return '#' + CSS.escape(el.id);
    const role = el.getAttribute('role');
    const text = (el.innerText || '').trim().slice(0, 40);
    if (role && text) return `[role="${role}"]:has-text("${text}")`;
    if ((el.tagName === 'BUTTON' || el.tagName === 'A') && text)
      return `${el.tagName.toLowerCase()}:has-text("${text}")`;
    const cls = [...el.classList].filter(c => !/^(active|hover|focus|is-|js-)/.test(c));
    if (cls.length) return '.' + cls[0];
    return el.tagName.toLowerCase();
  }

  document.addEventListener('click', (e) => {
    const el = e.target;
    const info = JSON.stringify({
      selector: bestSel(el),
      tag:  el.tagName,
      text: (el.innerText || '').trim().slice(0, 80),
      href: el.href || el.getAttribute('href') || null,
      url:  window.location.href,
    });
    if (window.__observeClick) window.__observeClick(info);
  }, true);
})();
"""


def observe_mode(page, ctx, reason: str) -> Path:
    """
    Switch the running browser to observe mode and block until it is closed.

    Parameters
    ----------
    page  : Playwright Page — the active page from the failing scraper
    ctx   : Playwright BrowserContext — the context to wait on
    reason: human-readable description of why the scraper gave up

    Returns
    -------
    Path to the saved session JSON file.
    """
    print()
    print("  " + "═" * 58)
    print(f"  ⚠  SCRAPER STUCK — {reason}")
    print("  " + "═" * 58)
    print("  Observe mode ON.  In the browser window:")
    print("    1. Navigate to the correct page if needed")
    print("    2. Perform the steps you want the scraper to do")
    print("    3. Every click and navigation is being recorded below")
    print("    4. Close the browser window when finished")
    print("  " + "═" * 58)
    print()

    # Show a browser alert so the user notices immediately
    try:
        page.evaluate(
            """(reason) => {
              alert(
                '⚠ SCRAPER STUCK — switching to Observe Mode\\n\\n'
                + 'Reason: ' + reason + '\\n\\n'
                + 'What to do:\\n'
                + '  1. Navigate to the correct page if needed\\n'
                + '  2. Click through the steps you want recorded\\n'
                + '  3. Close this browser window when done\\n\\n'
                + 'Everything you do is being logged in the terminal.'
              );
            }""",
            reason,
        )
    except Exception:
        pass  # page may be mid-navigation; terminal message is enough

    events: list[dict] = []
    t0 = time.time()

    def _ts() -> float:
        return round(time.time() - t0, 3)

    def _add(ev: dict) -> None:
        ev["t"] = _ts()
        events.append(ev)
        kind = ev.get("type", "")
        t    = ev["t"]
        if kind == "navigate":
            print(f"    [{t:7.2f}s] ► {ev.get('url', '')}", flush=True)
        elif kind == "click":
            txt = (' "' + ev["text"] + '"') if ev.get("text") else ""
            print(f"    [{t:7.2f}s] ● {ev.get('selector', '')}{txt}", flush=True)
        elif kind == "response" and ev.get("status", 200) >= 400:
            print(f"    [{t:7.2f}s] ✗ HTTP {ev['status']} {ev.get('url','')[:70]}", flush=True)

    # ── attach listeners to the existing page ──────────────────────────────
    def _on_nav(frame):
        if frame == page.main_frame:
            _add({"type": "navigate", "url": frame.url})

    def _on_response(response):
        ct = response.headers.get("content-type", "")
        _add({"type": "response", "status": response.status,
              "url": response.url, "content_type": ct})

    def _on_click(data: str):
        try:
            ev = json.loads(data)
            ev["type"] = "click"
            _add(ev)
        except Exception:
            pass

    def _inject():
        try:
            page.evaluate(_CLICK_JS)
        except Exception:
            pass

    page.on("framenavigated", _on_nav)
    page.on("response", _on_response)
    page.on("load", lambda: _inject())
    _inject()

    try:
        page.expose_function("__observeClick", _on_click)
    except Exception:
        pass  # already registered on this context

    # ── block until browser window is closed ───────────────────────────────
    try:
        ctx.wait_for_event("close", timeout=0)
    except KeyboardInterrupt:
        print("\n  (Ctrl+C — ending observe mode)")
    except Exception:
        pass

    # ── save session ───────────────────────────────────────────────────────
    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = SESSION_DIR / f"observe_{ts}.json"
    out.write_text(json.dumps({
        "recorded_at": datetime.now().isoformat(),
        "reason": reason,
        "duration_s": round(time.time() - t0, 1),
        "event_count": len(events),
        "events": events,
    }, indent=2, ensure_ascii=False))

    print(f"  ✅ Session saved → {out}")
    print(f"     {len(events)} events over {round(time.time()-t0):.0f}s")
    print()
    print("  To rebuild the scraper, paste the JSON above to your LLM:")
    print(f'  "Fix the scraper that failed with: {reason}"')
    print()
    return out
