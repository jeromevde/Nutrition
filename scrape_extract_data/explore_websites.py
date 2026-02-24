#!/usr/bin/env python3
"""
explore_websites.py — Interactive browser with full session recording
=====================================================================
Opens a real browser and silently records everything you do:
  - Every page navigation (URL changes)
  - Every click (with the best CSS selector for the clicked element)
  - Network requests / responses (including XHR, fetch, downloads)
  - DOM mutations (new elements appearing)

When you close the browser, the session is saved to a timestamped JSON file
in scrape_extract_data/sessions/.  You can then paste that file to an LLM
and ask it to write a Playwright scraper that reproduces your actions.

Usage:
    pip install playwright && playwright install chromium
    python scrape_extract_data/explore_websites.py
    python scrape_extract_data/explore_websites.py --url https://www.delhaize.be

The recording is printed live to the terminal while you browse.
Press Ctrl+C or just close the browser window to stop.

Workflow for fixing/building scrapers fast:
    1. Run this script and navigate to the relevant page
    2. Perform the actions you want to automate (log in, open receipts, etc.)
    3. Close the browser — session JSON is saved automatically
    4. Paste the session JSON into your LLM with the prompt:
       "Write a Playwright Python scraper that reproduces these user actions."
"""

from __future__ import annotations
import argparse
import json
import sys
import time
import re
from pathlib import Path
from datetime import datetime

HERE     = Path(__file__).parent          # scrape_extract_data/
REPO_ROOT = HERE.parent
SESSION_DIR = HERE / "sessions"
PROFILE_DIR = REPO_ROOT / ".browser_profile"

SESSION_DIR.mkdir(exist_ok=True)
PROFILE_DIR.mkdir(exist_ok=True)

# ── Selector generation (mirrors Playwright codegen logic) ────────────────────

# JS injected into every page to intercept clicks and report back selectors
_CLICK_MONITOR_JS = """
(() => {
  if (window.__explorerInjected) return;
  window.__explorerInjected = true;

  function bestSelector(el) {
    // 1. data-testid
    if (el.dataset && el.dataset.testid)
      return `[data-testid="${el.dataset.testid}"]`;
    // 2. aria-label
    if (el.getAttribute('aria-label'))
      return `[aria-label="${el.getAttribute('aria-label')}"]`;
    // 3. id
    if (el.id) return '#' + CSS.escape(el.id);
    // 4. role + text
    const role = el.getAttribute('role');
    const text = el.innerText ? el.innerText.trim().slice(0, 40) : '';
    if (role && text) return `[role="${role}"]:has-text("${text}")`;
    // 5. button / link text
    if ((el.tagName === 'BUTTON' || el.tagName === 'A') && text)
      return `${el.tagName.toLowerCase()}:has-text("${text}")`;
    // 6. class-based (first meaningful class only)
    const classes = [...el.classList].filter(c => !/^(active|hover|focus|is-|js-)/.test(c));
    if (classes.length) return `.${classes[0]}`;
    // 7. tag + nth
    const parent = el.parentElement;
    if (parent) {
      const siblings = [...parent.children].filter(c => c.tagName === el.tagName);
      if (siblings.length === 1) return el.tagName.toLowerCase();
      const idx = siblings.indexOf(el);
      return `${el.tagName.toLowerCase()}:nth-of-type(${idx + 1})`;
    }
    return el.tagName.toLowerCase();
  }

  document.addEventListener('click', (e) => {
    const el = e.target;
    const sel = bestSelector(el);
    const info = {
      type: 'click',
      selector: sel,
      tag: el.tagName,
      text: (el.innerText || '').trim().slice(0, 80),
      href: el.href || el.getAttribute('href') || null,
      url: window.location.href,
      ts: Date.now(),
    };
    if (window.__reportClick) window.__reportClick(JSON.stringify(info));
  }, true);
})();
"""

# ── Session recorder ──────────────────────────────────────────────────────────

class SessionRecorder:
    def __init__(self):
        self.events: list[dict] = []
        self._start = time.time()

    def _ts(self) -> float:
        return round(time.time() - self._start, 3)

    def log(self, event: dict):
        event.setdefault("t", self._ts())
        self.events.append(event)
        self._print(event)

    def _print(self, ev: dict):
        kind = ev.get("type", "?")
        t    = ev.get("t", 0)
        if kind == "navigate":
            print(f"  [{t:7.2f}s] ► navigate  {ev['url']}")
        elif kind == "click":
            txt = f" "{ev['text']}"" if ev.get("text") else ""
            print(f"  [{t:7.2f}s] ● click    {ev['selector']}{txt}")
        elif kind == "request":
            print(f"  [{t:7.2f}s] → request  {ev['method']} {ev['url'][:90]}")
        elif kind == "response":
            ct = ev.get("content_type", "")
            interesting = any(x in ct for x in ("json", "csv", "octet", "image"))
            if interesting or ev.get("status", 200) >= 400:
                print(f"  [{t:7.2f}s] ← response {ev['status']} {ev['url'][:80]}  [{ct}]")
        elif kind == "download":
            print(f"  [{t:7.2f}s] ↓ download  {ev['suggested_filename']}  url={ev['url'][:70]}")
        elif kind == "dom_mutation":
            print(f"  [{t:7.2f}s] ◆ dom       {ev['selector']} appeared")
        elif kind == "input":
            masked = "***" if ev.get("sensitive") else ev.get("value", "")
            print(f"  [{t:7.2f}s] ✎ input    {ev['selector']} = {masked!r}")

    def save(self, path: Path) -> None:
        summary = {
            "recorded_at": datetime.now().isoformat(),
            "duration_s": self._ts(),
            "event_count": len(self.events),
            "urls_visited": list(dict.fromkeys(
                e["url"] for e in self.events if e.get("url")
            )),
            "events": self.events,
        }
        path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
        print(f"\n✅ Session saved → {path}")
        print(f"   {len(self.events)} events over {self._ts():.0f}s")
        print(f"\n💡 To build a scraper from this session, run:")
        print(f"   Paste {path.name} into your LLM with the prompt:")
        print('   "Write a Playwright Python scraper that reproduces these user')
        print('    actions and saves the downloaded data to scrape_extract_data/."')


# ── Playwright hooks ──────────────────────────────────────────────────────────

def _attach_page_hooks(page, recorder: SessionRecorder):
    """Attach all monitoring hooks to a Playwright page."""

    # Navigation
    def _on_nav(frame):
        if frame == page.main_frame:
            recorder.log({"type": "navigate", "url": frame.url})

    page.on("framenavigated", _on_nav)

    # Network requests (log all; only print interesting ones — see _print)
    def _on_request(request):
        recorder.log({
            "type": "request",
            "method": request.method,
            "url": request.url,
            "resource_type": request.resource_type,
        })

    def _on_response(response):
        ct = response.headers.get("content-type", "")
        recorder.log({
            "type": "response",
            "status": response.status,
            "url": response.url,
            "content_type": ct,
        })

    page.on("request", _on_request)
    page.on("response", _on_response)

    # Downloads
    def _on_download(download):
        recorder.log({
            "type": "download",
            "suggested_filename": download.suggested_filename,
            "url": download.url,
        })

    page.context.on("download", _on_download)

    # Click interception via injected JS
    def _on_click(data: str):
        try:
            ev = json.loads(data)
            ev["type"] = "click"
            recorder.log(ev)
        except Exception:
            pass

    try:
        page.expose_function("__reportClick", _on_click)
    except Exception:
        pass  # already exposed on this page

    # Inject monitoring JS after every navigation
    def _inject():
        try:
            page.evaluate(_CLICK_MONITOR_JS)
        except Exception:
            pass

    page.on("load", lambda: _inject())
    _inject()


def _watch_for_new_pages(context, recorder: SessionRecorder):
    """Attach hooks to any new tabs/popups the user opens."""
    def _on_page(page):
        _attach_page_hooks(page, recorder)
    context.on("page", _on_page)


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Record a browser session to help build/fix scrapers"
    )
    parser.add_argument(
        "--url", default="about:blank",
        help="Starting URL (default: blank — navigate manually)",
    )
    parser.add_argument(
        "--out", default=None,
        help="Output JSON path (default: sessions/<timestamp>.json)",
    )
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright not installed. Run:\n  pip install playwright && playwright install chromium")
        return 1

    session_path = Path(args.out) if args.out else (
        SESSION_DIR / f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )

    recorder = SessionRecorder()
    print("🔴 Recording session — browse normally, then close the window or press Ctrl+C\n")

    try:
        with sync_playwright() as pw:
            ctx = pw.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                headless=False,
                viewport={"width": 1400, "height": 900},
                args=["--disable-blink-features=AutomationControlled"],
                # Accept downloads so we can log them
                accept_downloads=True,
            )

            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            _attach_page_hooks(page, recorder)
            _watch_for_new_pages(ctx, recorder)

            if args.url and args.url != "about:blank":
                page.goto(args.url, wait_until="domcontentloaded")

            # Keep alive until the browser or user closes
            print("  (Browser is open — do your thing, then close the window)\n")
            while True:
                try:
                    # Poll whether any pages are still open
                    if not ctx.pages:
                        break
                    time.sleep(0.5)
                except Exception:
                    break

    except KeyboardInterrupt:
        print("\n  (Ctrl+C received)")
    except Exception as e:
        if "Target page, context or browser has been closed" not in str(e):
            print(f"  Session ended: {e}")

    recorder.save(session_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
