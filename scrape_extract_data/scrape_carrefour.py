#!/usr/bin/env python3
"""
scrape_carrefour.py — Carrefour frequently-purchased items scraper
==================================================================
Opens the Carrefour "Frequently Purchased" page, waits for login, scrapes
all product names. Automatically switches to OBSERVE MODE if 0 items are found
(selector likely changed).

Usage:
    python scrape_extract_data/scrape_carrefour.py

Output: scrape_extract_data/carrefour/carrefour_favorites.csv
"""

from __future__ import annotations
import csv
import sys
import time
from pathlib import Path

HERE        = Path(__file__).parent          # scrape_extract_data/sys.path.insert(0, str(HERE))                 # allow: from _observe import ...REPO_ROOT   = HERE.parent
DATA_DIR    = HERE / "carrefour"
PROFILE_DIR = REPO_ROOT / ".browser_profile"
DATA_DIR.mkdir(parents=True, exist_ok=True)
PROFILE_DIR.mkdir(exist_ok=True)

_t0 = time.time()
def _log(msg: str) -> None:
    print(f"  [{time.time()-_t0:6.1f}s] {msg}", flush=True)


def _launch_browser(pw):
    return pw.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=False,
        viewport={"width": 1280, "height": 900},
        args=["--disable-blink-features=AutomationControlled"],
    )


def scrape_carrefour(pw) -> None:
    from _observe import observe_mode

    print("═══ Carrefour ═══")
    ctx = _launch_browser(pw)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    page.goto(
        "https://www.carrefour.be/nl/frequentlypurchased",
        wait_until="domcontentloaded",
    )
    print("  → Browser opened. Please log in if needed.")
    _log("waiting for .product-tile (up to 5 min) …")

    try:
        page.wait_for_selector(".product-tile", timeout=300_000)
    except Exception:
        _log("✗ Timed out — switching to observe mode")
        observe_mode(page, ctx, "no .product-tile appeared after login")
        return

    _log("scrolling to load all products …")
    prev_count = 0
    for _ in range(50):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(800)
        tiles = page.query_selector_all(".product-tile")
        if len(tiles) == prev_count:
            break
        prev_count = len(tiles)

    tiles = page.query_selector_all(".product-tile")
    _log(f"found {len(tiles)} product tiles")

    items: list[dict] = []
    for tile in tiles:
        name_el  = tile.query_selector("span.d-lg-none.mobile-name")
        brand_el = tile.query_selector(".brand-wrapper a")
        name  = name_el.text_content().strip()  if name_el  else ""
        brand = brand_el.text_content().strip() if brand_el else ""
        if name:
            items.append({"product_name": f"{brand} - {name}" if brand else name})

    if not items:
        reason = "0 product names extracted — name/brand selectors likely changed"
        _log(f"✗ STUCK: {reason}")
        observe_mode(page, ctx, reason)
        return

    out_path = DATA_DIR / "carrefour_favorites.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["product_name"])
        w.writeheader()
        w.writerows(items)

    _log(f"saved {len(items)} items → {out_path}")
    ctx.close()


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright not installed:\n  pip install playwright && playwright install chromium")
        return 1

    with sync_playwright() as pw:
        scrape_carrefour(pw)

    print("\nNext: build the nutrition mapping:")
    print("  cd nutrient_analysis && python 01_build_mapping.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
