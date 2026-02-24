#!/usr/bin/env python3
"""
scrape_groceries.py — Automated grocery receipt/favorites scraper
=================================================================
Uses Playwright to open real browser windows for each supermarket.
The user authenticates manually, then the script auto-scrapes the data.

Usage:
    pip install playwright pandas
    playwright install chromium
    python scrape_groceries.py                   # all stores
    python scrape_groceries.py --store delhaize   # single store
    python scrape_groceries.py --store carrefour
    python scrape_groceries.py --store colruyt

What it does:
  - Delhaize:   Opens My Receipts page → downloads ticket images as base64
                 → OCRs them or saves raw CSVs (product_name, price, barcode)
  - Carrefour:  Opens Frequently Purchased page → scrapes product names
  - Colruyt:    Opens My Products page → scrapes product names + weights

The browser stays open longer for you to log in. Once the expected page
elements are detected, scraping begins automatically.
"""

from __future__ import annotations
import argparse, csv, re, time, json, sys
from pathlib import Path
from datetime import datetime

# ── Paths ────────────────────────────────────────────────────────────────────
SCRAPERS_DIR   = Path(__file__).parent / "scrapers"
DELHAIZE_DIR   = SCRAPERS_DIR / "delhaize" / "tickets"
CARREFOUR_DIR  = SCRAPERS_DIR / "carrefour"
COLRUYT_DIR    = SCRAPERS_DIR / "colruyt"

# Ensure output dirs exist
for d in (DELHAIZE_DIR, CARREFOUR_DIR, COLRUYT_DIR):
    d.mkdir(parents=True, exist_ok=True)

# Browser profile dir – keeps cookies/sessions between runs
PROFILE_DIR = Path(__file__).parent / ".browser_profile"
PROFILE_DIR.mkdir(exist_ok=True)


def _launch_browser(pw):
    """Launch a persistent Chromium context so login sessions are remembered."""
    return pw.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=False,
        viewport={"width": 1280, "height": 900},
        args=["--disable-blink-features=AutomationControlled"],
    )


# ── Delhaize ─────────────────────────────────────────────────────────────────

def scrape_delhaize(pw) -> None:
    """
    Navigate to Delhaize My Receipts page.
    Wait for user to log in, then iterate receipts, open each modal,
    extract the ticket image, and save it.
    """
    print("\n═══ Delhaize ═══")
    ctx = _launch_browser(pw)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    page.goto("https://www.delhaize.be/nl/my-account/loyalty/tickets", wait_until="domcontentloaded")
    print("  → Browser opened. Please log in if needed.")
    print("  → Waiting for receipts to appear …")

    # Wait for at least one receipt row (up to 5 minutes for login)
    try:
        page.wait_for_selector('[data-testid="my-receipts-list-row"]', timeout=300_000)
    except Exception:
        print("  ✗ Timed out waiting for receipts page. Did you log in?")
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

    # Re-query rows AFTER expanding (DOM may have changed)
    rows = page.query_selector_all('[data-testid="my-receipts-list-row"]')
    print(f"  Found {len(rows)} receipts")

    MODAL_SEL = '[data-testid="modal-main-content"]'

    def _close_modal():
        """Close the Delhaize receipt modal and wait for it to disappear."""
        # Try specific close buttons first, then fall back to Escape
        CLOSE_SELECTORS = [
            '[data-testid="modal-main-content"] [aria-label*="sluit" i]',
            '[data-testid="modal-main-content"] [aria-label*="close" i]',
            '[data-testid="modal-close-button"]',
            '[data-testid*="close"]',
        ]
        closed = False
        for sel in CLOSE_SELECTORS:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                try:
                    btn.click()
                    closed = True
                    break
                except Exception:
                    continue

        if not closed:
            page.keyboard.press("Escape")

        # Wait for the modal to actually vanish
        try:
            page.wait_for_selector(MODAL_SEL, state="hidden", timeout=4000)
        except Exception:
            page.keyboard.press("Escape")
            page.wait_for_timeout(800)

    saved = 0
    for i in range(len(rows)):
        # Re-query the row by index each time — avoids stale element references
        # after the DOM is mutated by modal open/close
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

        # Open receipt modal
        btn = row.query_selector('[data-testid="my-receipts-list-button"]')
        if not btn:
            print(f"  [{i+1}/{len(rows)}] No button for {date_text}, skipping")
            continue

        btn.scroll_into_view_if_needed()
        btn.click()

        # Wait for the Delhaize modal content to appear
        try:
            page.wait_for_selector(MODAL_SEL, state="visible", timeout=8000)
        except Exception:
            print(f"  [{i+1}/{len(rows)}] Modal didn't open for {date_text}")
            _close_modal()
            continue

        # Wait for the ticket image to load inside the modal (up to 8 s)
        img = None
        IMG_SELECTORS = (
            'img[src^="data:image/jpeg;base64"]',
            'img[src^="data:image/png;base64"]',
            'div[data-testid="modal-main-content"] img[src]',
            'img[alt*="Kasticket" i]',
            'img[alt*="kassaticket" i]',
            'img[alt*="ticket" i]',
        )
        for sel in IMG_SELECTORS:
            try:
                page.wait_for_selector(sel, timeout=8000)
                img = page.query_selector(sel)
                if img:
                    break
            except Exception:
                continue

        if img:
            src = img.get_attribute("src") or ""
            if src.startswith("data:image"):
                import base64 as _b64
                b64 = src.split(",", 1)[1] if "," in src else src
                img_path.write_bytes(_b64.b64decode(b64))
                print(f"  [{i+1}/{len(rows)}] Saved {img_path.name}")
                saved += 1
            else:
                print(f"  [{i+1}/{len(rows)}] Image found but not base64 for {date_text}")
        else:
            print(f"  [{i+1}/{len(rows)}] No image loaded for {date_text}")

        # Always close the modal before moving on
        _close_modal()
        page.wait_for_timeout(400)

    print(f"  Done — saved {saved} new receipt images")
    ctx.close()


# ── Carrefour ────────────────────────────────────────────────────────────────

def scrape_carrefour(pw) -> None:
    """
    Navigate to Carrefour Frequently Purchased page.
    Wait for login, then scrape product names + brands.
    """
    print("\n═══ Carrefour ═══")
    ctx = _launch_browser(pw)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    page.goto("https://www.carrefour.be/nl/frequentlypurchased", wait_until="domcontentloaded")
    print("  → Browser opened. Please log in if needed.")
    print("  → Waiting for product tiles …")

    try:
        page.wait_for_selector(".product-tile", timeout=300_000)
    except Exception:
        print("  ✗ Timed out. Did you log in and navigate to the page?")
        ctx.close()
        return

    # Scroll down to load all products
    print("  Scrolling to load all products …")
    prev_count = 0
    for _ in range(50):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(800)
        tiles = page.query_selector_all(".product-tile")
        if len(tiles) == prev_count:
            break
        prev_count = len(tiles)

    tiles = page.query_selector_all(".product-tile")
    print(f"  Found {len(tiles)} product tiles")

    items: list[dict] = []
    for tile in tiles:
        name_el = tile.query_selector("span.d-lg-none.mobile-name")
        brand_el = tile.query_selector(".brand-wrapper a")
        name = name_el.text_content().strip() if name_el else ""
        brand = brand_el.text_content().strip() if brand_el else ""
        if name:
            items.append({"product_name": f"{brand} - {name}" if brand else name})

    out_path = CARREFOUR_DIR / "favorite_items.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["product_name"])
        w.writeheader()
        w.writerows(items)

    print(f"  Saved {len(items)} items → {out_path}")
    ctx.close()


# ── Colruyt ──────────────────────────────────────────────────────────────────

def scrape_colruyt(pw) -> None:
    """
    Navigate to Colruyt My Products / favorites page.
    Wait for login, then scrape product cards.
    """
    print("\n═══ Colruyt ═══")
    ctx = _launch_browser(pw)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    page.goto("https://www.colruyt.be/nl/mijn-boodschappen/favorieten", wait_until="domcontentloaded")
    print("  → Browser opened. Please log in if needed.")
    print("  → Waiting for product cards …")

    try:
        page.wait_for_selector("a.card.card--article, .product-card, .favorite-item",
                               timeout=300_000)
    except Exception:
        print("  ✗ Timed out. Did you log in?")
        ctx.close()
        return

    # Scroll to load all
    print("  Scrolling to load all products …")
    prev_count = 0
    for _ in range(50):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(800)
        cards = page.query_selector_all("a.card.card--article, .product-card, .favorite-item")
        if len(cards) == prev_count:
            break
        prev_count = len(cards)

    cards = page.query_selector_all("a.card.card--article, .product-card, .favorite-item")
    print(f"  Found {len(cards)} product cards")

    items: list[dict] = []
    for card in cards:
        name_el = card.query_selector(".card__text, .product-name")
        weight_el = card.query_selector(".card__quantity, .product-weight")
        name = name_el.text_content().strip() if name_el else ""
        weight = weight_el.text_content().strip() if weight_el else ""
        full = f"{name} - {weight}" if weight else name
        if full.strip():
            items.append({"product_name": full})

    out_path = COLRUYT_DIR / "colruyt_favorites.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["product_name"])
        w.writeheader()
        w.writerows(items)

    print(f"  Saved {len(items)} items → {out_path}")
    ctx.close()


# ── Main ─────────────────────────────────────────────────────────────────────

STORES = {
    "delhaize":  scrape_delhaize,
    "carrefour": scrape_carrefour,
    "colruyt":   scrape_colruyt,
}

def main():
    parser = argparse.ArgumentParser(description="Scrape grocery receipts/favorites via browser")
    parser.add_argument(
        "--store", choices=list(STORES.keys()),
        help="Scrape a single store (default: all)",
    )
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright not installed. Run:\n  pip install playwright && playwright install chromium")
        return 1

    targets = [args.store] if args.store else list(STORES.keys())

    with sync_playwright() as pw:
        for store in targets:
            try:
                STORES[store](pw)
            except Exception as e:
                print(f"  ✗ {store} failed: {e}")

    print("\nAll done. Run the nutrient analysis pipeline next:")
    print("  cd nutrient_analysis")
    print("  python 01_build_mapping.py")
    print("  python 02_nutrition_report.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
