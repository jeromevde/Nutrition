#!/usr/bin/env python3
"""
scrape_delhaize.py — Delhaize receipt image scraper
====================================================
Opens the Delhaize "My Receipts" page in a real browser,
waits for you to log in, then downloads every ticket as a .jpg.

Usage:
    pip install playwright && playwright install chromium
    python scrape_delhaize.py

Output:
    scrapers/delhaize/tickets/<yyyy>_<mm>_<dd>.jpg

After scraping, OCR the images:
    python batch_ocr_receipts.py
"""

from __future__ import annotations
import sys
from pathlib import Path

# Repo root = two levels up from this file
REPO_ROOT     = Path(__file__).parent.parent
DELHAIZE_DIR  = REPO_ROOT / "scrapers" / "delhaize" / "tickets"
PROFILE_DIR   = REPO_ROOT / ".browser_profile"

DELHAIZE_DIR.mkdir(parents=True, exist_ok=True)
PROFILE_DIR.mkdir(exist_ok=True)


def _launch_browser(pw):
    """Launch a persistent Chromium context so login sessions are remembered."""
    return pw.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=False,
        viewport={"width": 1280, "height": 900},
        args=["--disable-blink-features=AutomationControlled"],
    )


def scrape_delhaize(pw) -> None:
    """
    Navigate to Delhaize My Receipts page, wait for login,
    then iterate receipts and save each ticket image as a .jpg.
    """
    print("═══ Delhaize ═══")
    ctx = _launch_browser(pw)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    page.goto(
        "https://www.delhaize.be/nl/my-account/loyalty/tickets",
        wait_until="domcontentloaded",
    )
    print("  → Browser opened. Please log in if needed.")
    print("  → Waiting for receipts to appear …")

    try:
        page.wait_for_selector('[data-testid="my-receipts-list-row"]', timeout=300_000)
    except Exception:
        print("  ✗ Timed out waiting for receipts. Did you log in?")
        ctx.close()
        return

    # Expand all collapsed months
    print("  Expanding all months …")
    toggles = page.query_selector_all(
        '[data-testid="collapsable-button-toggle"][aria-expanded="false"]'
    )
    for toggle in toggles:
        toggle.scroll_into_view_if_needed()
        toggle.click()
        page.wait_for_timeout(800)
    page.wait_for_timeout(1500)

    rows = page.query_selector_all('[data-testid="my-receipts-list-row"]')
    print(f"  Found {len(rows)} receipts")

    # Timings mirrored from the working scrape_delhaize_tickets.js
    MODAL_OPEN_WAIT  = 1500   # ms to let image load after clicking receipt
    MODAL_CLOSE_WAIT = 1000   # ms after clicking close before next receipt

    def _close_modal():
        close = (
            page.query_selector('[aria-label*="Sluit"]') or
            page.query_selector('[aria-label*="Close"]') or
            page.query_selector('[aria-label*="sluiten"]') or
            page.query_selector('[role="dialog"] button') or
            page.query_selector('button.close, .modal-close')
        )
        if close:
            close.click()
        else:
            page.keyboard.press("Escape")
        page.wait_for_timeout(MODAL_CLOSE_WAIT)

    import base64 as _b64

    saved = 0
    for i in range(len(rows)):
        all_rows = page.query_selector_all('[data-testid="my-receipts-list-row"]')
        if i >= len(all_rows):
            break
        row = all_rows[i]

        date_el = row.query_selector('[data-testid="my-receipts-date"]')
        if not date_el:
            continue
        date_text = date_el.text_content().strip()
        parts = date_text.split("/")
        if len(parts) != 3:
            continue
        dd, mm, yyyy = parts
        img_path = DELHAIZE_DIR / f"{yyyy}_{mm}_{dd}.jpg"

        if img_path.exists():
            print(f"  [{i+1}/{len(rows)}] Already saved {img_path.name}, skipping")
            continue

        btn = row.query_selector('[data-testid="my-receipts-list-button"]')
        if not btn:
            print(f"  [{i+1}/{len(rows)}] No button for {date_text}, skipping")
            continue

        btn.scroll_into_view_if_needed()
        btn.click()
        page.wait_for_timeout(MODAL_OPEN_WAIT)

        # Query image globally — same priority order as the working JS scraper
        img = (
            page.query_selector('img[src^="data:image/jpeg;base64"]') or
            page.query_selector('img[src^="data:image/png;base64"]') or
            page.query_selector('div[data-testid="modal-main-content"] img') or
            page.query_selector('img[alt*="Kasticket" i]') or
            page.query_selector('img[alt*="kassaticket" i]') or
            page.query_selector('img[alt*="ticket" i]') or
            page.query_selector('[role="dialog"] img[src^="data:image"]')
        )

        if img:
            src = img.get_attribute("src") or ""
            if src.startswith("data:image"):
                b64 = src.split(",", 1)[1] if "," in src else src
                img_path.write_bytes(_b64.b64decode(b64))
                print(f"  [{i+1}/{len(rows)}] Saved {img_path.name}")
                saved += 1
            else:
                print(f"  [{i+1}/{len(rows)}] Image not base64 for {date_text}")
        else:
            print(f"  [{i+1}/{len(rows)}] No image found for {date_text} (modal too slow?)")

        _close_modal()

    print(f"  Done — saved {saved} new receipt images to {DELHAIZE_DIR}")
    ctx.close()


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright not installed. Run:\n  pip install playwright && playwright install chromium")
        return 1

    with sync_playwright() as pw:
        scrape_delhaize(pw)

    print("\nNext step — OCR the ticket images:")
    print("  python scrape_extract_data/batch_ocr_receipts.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
