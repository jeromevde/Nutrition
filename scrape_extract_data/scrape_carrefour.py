#!/usr/bin/env python3
"""
scrape_carrefour.py — Carrefour frequently-purchased items scraper
==================================================================
Opens the Carrefour "Frequently Purchased" page in a real browser,
waits for you to log in, then scrapes all product names and brands.

Usage:
    pip install playwright && playwright install chromium
    python scrape_carrefour.py

Output:
    scrapers/carrefour/favorite_items.csv   (columns: product_name)
"""

from __future__ import annotations
import csv
import sys
from pathlib import Path

REPO_ROOT     = Path(__file__).parent.parent
CARREFOUR_DIR = REPO_ROOT / "scrapers" / "carrefour"
PROFILE_DIR   = REPO_ROOT / ".browser_profile"

CARREFOUR_DIR.mkdir(parents=True, exist_ok=True)
PROFILE_DIR.mkdir(exist_ok=True)


def _launch_browser(pw):
    """Launch a persistent Chromium context so login sessions are remembered."""
    return pw.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=False,
        viewport={"width": 1280, "height": 900},
        args=["--disable-blink-features=AutomationControlled"],
    )


def scrape_carrefour(pw) -> None:
    """
    Navigate to Carrefour Frequently Purchased page,
    wait for login, then scrape product names + brands.
    """
    print("═══ Carrefour ═══")
    ctx = _launch_browser(pw)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    page.goto(
        "https://www.carrefour.be/nl/frequentlypurchased",
        wait_until="domcontentloaded",
    )
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
        name_el  = tile.query_selector("span.d-lg-none.mobile-name")
        brand_el = tile.query_selector(".brand-wrapper a")
        name  = name_el.text_content().strip()  if name_el  else ""
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


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright not installed. Run:\n  pip install playwright && playwright install chromium")
        return 1

    with sync_playwright() as pw:
        scrape_carrefour(pw)

    print("\nNext step — build the nutrition mapping:")
    print("  cd nutrient_analysis && python 01_build_mapping.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
