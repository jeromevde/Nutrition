#!/usr/bin/env python3
"""
scrape_delhaize.py — Delhaize receipt image scraper
====================================================
Opens the Delhaize "My Receipts" page in a real browser, waits for login,
then iterates every receipt and saves the ticket image as a .jpg.

If the scraper gets stuck (3+ consecutive failures to extract an image),
it automatically switches to OBSERVE MODE: records your manual actions in
the browser and saves a session JSON you can feed to an LLM to fix it.

Usage:
    pip install playwright && playwright install chromium
    python scrape_extract_data/scrape_delhaize.py

Output: scrape_extract_data/delhaize/<yyyy>_<mm>_<dd>.jpg
"""

from __future__ import annotations
import base64
import sys
import time
from pathlib import Path

HERE         = Path(__file__).parent          # scrape_extract_data/
sys.path.insert(0, str(HERE))                 # allow: from _observe import ...
REPO_ROOT    = HERE.parent
DATA_DIR     = HERE / "delhaize"
PROFILE_DIR  = REPO_ROOT / ".browser_profile"
DATA_DIR.mkdir(parents=True, exist_ok=True)
PROFILE_DIR.mkdir(exist_ok=True)

# How many consecutive receipt failures before we give up and go observe mode
FAILURE_THRESHOLD = 3
MODAL_OPEN_WAIT   = 1500   # ms after clicking receipt
MODAL_CLOSE_WAIT  = 1000   # ms after closing modal

_t0 = time.time()
def _log(msg: str) -> None:
    print(f"  [{time.time()-_t0:6.1f}s] {msg}", flush=True)

IMG_SELECTORS = [
    'img[src^="data:image/jpeg;base64"]',
    'img[src^="data:image/png;base64"]',
    'div[data-testid="modal-main-content"] img',
    'img[alt*="Kasticket" i]',
    'img[alt*="kassaticket" i]',
    'img[alt*="ticket" i]',
    '[role="dialog"] img[src^="data:image"]',
]


def _launch_browser(pw):
    return pw.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=False,
        viewport={"width": 1280, "height": 900},
        args=["--disable-blink-features=AutomationControlled"],
    )


def scrape_delhaize(pw) -> None:
    from _observe import observe_mode

    print("═══ Delhaize ═══")
    ctx = _launch_browser(pw)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    page.goto(
        "https://www.delhaize.be/nl/my-account/loyalty/tickets",
        wait_until="domcontentloaded",
    )
    print("  → Browser opened. Please log in if needed.")
    _log("waiting for [data-testid=my-receipts-list-row] (up to 5 min) …")

    try:
        page.wait_for_selector('[data-testid="my-receipts-list-row"]', timeout=300_000)
    except Exception:
        _log("✗ Timed out — switching to observe mode")
        observe_mode(page, ctx, "receipts page never appeared")
        return

    # Expand collapsed months
    _log("expanding collapsed month sections …")
    toggles = page.query_selector_all(
        '[data-testid="collapsable-button-toggle"][aria-expanded="false"]'
    )
    _log(f"found {len(toggles)} collapsed toggle(s)")
    for toggle in toggles:
        toggle.scroll_into_view_if_needed()
        toggle.click()
        page.wait_for_timeout(800)
    page.wait_for_timeout(1500)

    rows = page.query_selector_all('[data-testid="my-receipts-list-row"]')
    _log(f"found {len(rows)} receipts")

    def _close_modal():
        close = (
            page.query_selector('[aria-label*="Sluit"]') or
            page.query_selector('[aria-label*="Close"]') or
            page.query_selector('[aria-label*="sluiten"]') or
            page.query_selector('[role="dialog"] button') or
            page.query_selector('button.close, .modal-close')
        )
        if close:
            lbl = close.get_attribute("aria-label") or close.tag_name or "?"
            _log(f"  close modal ← [{lbl}]")
            try:
                # force=True bypasses the modal-overlay div that intercepts pointer events
                close.click(force=True)
            except Exception:
                page.keyboard.press("Escape")
        else:
            _log("  close modal ← Escape (no close button found)")
            page.keyboard.press("Escape")
        page.wait_for_timeout(MODAL_CLOSE_WAIT)

    saved = 0
    consecutive_failures = 0

    for i in range(len(rows)):
        # ── stuck detection ──────────────────────────────────────────────
        if consecutive_failures >= FAILURE_THRESHOLD:
            reason = (
                f"{consecutive_failures} consecutive receipts had no extractable "
                f"image — selectors likely changed"
            )
            _log(f"✗ STUCK: {reason}")
            observe_mode(page, ctx, reason)
            return

        all_rows = page.query_selector_all('[data-testid="my-receipts-list-row"]')
        if i >= len(all_rows):
            break
        row = all_rows[i]

        date_el = row.query_selector('[data-testid="my-receipts-date"]')
        if not date_el:
            _log(f"[{i+1}/{len(rows)}] no date element — skipping row")
            consecutive_failures += 1
            continue
        date_text = date_el.text_content().strip()
        parts = date_text.split("/")
        if len(parts) != 3:
            _log(f"[{i+1}/{len(rows)}] unexpected date format: {date_text!r}")
            consecutive_failures += 1
            continue
        dd, mm, yyyy = parts
        img_path = DATA_DIR / f"{yyyy}_{mm}_{dd}.jpg"

        if img_path.exists():
            _log(f"[{i+1}/{len(rows)}] {img_path.name} already exists, skipping")
            consecutive_failures = 0   # existing file = things are working
            continue

        btn = row.query_selector('[data-testid="my-receipts-list-button"]')
        if not btn:
            _log(f"[{i+1}/{len(rows)}] no button for {date_text}")
            consecutive_failures += 1
            continue

        _log(f"[{i+1}/{len(rows)}] {date_text} — clicking receipt")
        btn.scroll_into_view_if_needed()
        btn.click()
        _log(f"[{i+1}/{len(rows)}] waiting {MODAL_OPEN_WAIT}ms for modal …")
        page.wait_for_timeout(MODAL_OPEN_WAIT)

        img = None
        for sel in IMG_SELECTORS:
            img = page.query_selector(sel)
            if img:
                _log(f"[{i+1}/{len(rows)}] image found via: {sel}")
                break
        if not img:
            _log(f"[{i+1}/{len(rows)}] ✗ no image matched any selector")
            consecutive_failures += 1
            _close_modal()
            continue

        src = img.get_attribute("src") or ""
        if src.startswith("data:image"):
            b64 = src.split(",", 1)[1] if "," in src else src
            img_path.write_bytes(base64.b64decode(b64))
            _log(f"[{i+1}/{len(rows)}] ✓ saved {img_path.name}")
            saved += 1
            consecutive_failures = 0
        else:
            _log(f"[{i+1}/{len(rows)}] image src is not base64 for {date_text}")
            consecutive_failures += 1

        _close_modal()

    _log(f"done — saved {saved} new images to {DATA_DIR}")
    ctx.close()


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright not installed:\n  pip install playwright && playwright install chromium")
        return 1

    with sync_playwright() as pw:
        scrape_delhaize(pw)

    print("\nNext: OCR the ticket images:")
    print("  python scrape_extract_data/batch_ocr_receipts.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
