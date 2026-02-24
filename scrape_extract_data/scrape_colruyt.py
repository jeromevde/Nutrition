#!/usr/bin/env python3
"""
scrape_colruyt.py — Colruyt favourites scraper
===============================================
Opens the Colruyt "My Products / Favourites" page in a real browser,
waits for you to log in, then scrapes all product cards.

Usage:
    pip install playwright && playwright install chromium
    python scrape_colruyt.py

Output:
    scrape_extract_data/colruyt_favorites.csv   (columns: product_name)
"""

from __future__ import annotations
import csv
import sys
from pathlib import Path

HERE        = Path(__file__).parent                       # scrape_extract_data/
REPO_ROOT   = HERE.parent
PROFILE_DIR = REPO_ROOT / ".browser_profile"

PROFILE_DIR.mkdir(exist_ok=True)


def _launch_browser(pw):
    """Launch a persistent Chromium context so login sessions are remembered."""
    return pw.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=False,
        viewport={"width": 1280, "height": 900},
        args=["--disable-blink-features=AutomationControlled"],
    )


def scrape_colruyt(pw) -> None:
    """
    Navigate to Colruyt My Products / Favourites page,
    wait for login, then scrape product cards.
    """
    print("═══ Colruyt ═══")
    ctx = _launch_browser(pw)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    page.goto(
        "https://www.colruyt.be/nl/mijn-boodschappen/favorieten",
        wait_until="domcontentloaded",
    )
    print("  → Browser opened. Please log in if needed.")
    print("  → Waiting for product cards …")

    try:
        page.wait_for_selector(
            "a.card.card--article, .product-card, .favorite-item",
            timeout=300_000,
        )
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
        cards = page.query_selector_all(
            "a.card.card--article, .product-card, .favorite-item"
        )
        if len(cards) == prev_count:
            break
        prev_count = len(cards)

    cards = page.query_selector_all(
        "a.card.card--article, .product-card, .favorite-item"
    )
    print(f"  Found {len(cards)} product cards")

    items: list[dict] = []
    for card in cards:
        name_el   = card.query_selector(".card__text, .product-name")
        weight_el = card.query_selector(".card__quantity, .product-weight")
        name   = name_el.text_content().strip()   if name_el   else ""
        weight = weight_el.text_content().strip() if weight_el else ""
        full = f"{name} - {weight}" if weight else name
        if full.strip():
            items.append({"product_name": full})

    out_path = HERE / "colruyt_favorites.csv"
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
        scrape_colruyt(pw)

    print("\nNext step — build the nutrition mapping:")
    print("  cd nutrient_analysis && python 01_build_mapping.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
