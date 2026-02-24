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
import argparse, csv, re, time, json, sys, logging
from pathlib import Path
from datetime import datetime

# ── Paths ────────────────────────────────────────────────────────────────────
SCRAPERS_DIR   = Path(__file__).parent / "scrapers"
DELHAIZE_DIR   = SCRAPERS_DIR / "delhaize" / "tickets"
CARREFOUR_DIR  = SCRAPERS_DIR / "carrefour"
COLRUYT_DIR    = SCRAPERS_DIR / "colruyt"
LOG_FILE       = Path(__file__).parent / "scraper.log"

# Module-level logger — configured in main() via _setup_logging()
log = logging.getLogger("scraper")

# Ensure output dirs exist
for d in (DELHAIZE_DIR, CARREFOUR_DIR, COLRUYT_DIR):
    d.mkdir(parents=True, exist_ok=True)

# Browser profile dir – keeps cookies/sessions between runs
PROFILE_DIR = Path(__file__).parent / ".browser_profile"
PROFILE_DIR.mkdir(exist_ok=True)


# ── Logging ──────────────────────────────────────────────────────────────────

def _setup_logging(verbose: bool = False) -> None:
    """Configure file + console logging.

    The log file (scraper.log) always captures DEBUG-level messages so every
    selector probe, DOM snapshot, and timing detail is preserved for later
    analysis.  The console shows INFO normally; pass --verbose to also see
    DEBUG on stdout.
    """
    log.setLevel(logging.DEBUG)

    # Rotating-friendly plain file — always DEBUG
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-5s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    log.addHandler(fh)

    # Console — INFO by default, DEBUG with --verbose
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.DEBUG if verbose else logging.INFO)
    ch.setFormatter(logging.Formatter("  %(message)s"))
    log.addHandler(ch)


def _try_selectors(page, selectors: list[str], label: str = ""):
    """Try each CSS selector in order; log every hit/miss.

    This makes it trivial to spot which fallback fired (or that nothing
    matched) — useful for detecting site changes and simplifying the list
    once a single selector proves stable.

    Returns the first matching ElementHandle, or None.
    """
    tag = f"[{label}] " if label else ""
    for sel in selectors:
        el = page.query_selector(sel)
        if el:
            log.debug(f"{tag}✓ matched {sel!r}")
            return el
        log.debug(f"{tag}✗ no match {sel!r}")
    log.warning(f"{tag}no selector matched from {selectors}")
    return None


def _dom_snapshot(page, label: str = "") -> None:
    """Dump a structural snapshot of the page to the log file (DEBUG level).

    Captures:
    - Every unique data-testid attribute (sorted) — lets you see new/removed
      testids when the site updates its markup.
    - Every element with an aria-label — reveals close/action buttons.
    - Every element with a role= attribute — reveals dialogs, regions, etc.
    - The outer HTML of every modal-like container (base64 stripped) — lets
      you see the exact modal structure without wading through image data.

    All output goes to scraper.log; nothing is printed to the console unless
    --verbose is active.
    """
    tag = f"[{label}] " if label else ""

    try:
        testids: list[str] = page.evaluate("""
            () => [...new Set(
                [...document.querySelectorAll('[data-testid]')]
                .map(el => el.getAttribute('data-testid'))
                .filter(Boolean)
            )].sort()
        """)
        log.debug(f"{tag}data-testid values ({len(testids)}): {testids}")
    except Exception as e:
        log.debug(f"{tag}data-testid query failed: {e}")

    try:
        aria_els: list[dict] = page.evaluate("""
            () => [...document.querySelectorAll('[aria-label]')].map(el => ({
                tag: el.tagName,
                role: el.getAttribute('role') || '',
                label: el.getAttribute('aria-label'),
                visible: el.offsetParent !== null
            }))
        """)
        log.debug(f"{tag}aria-label elements: {aria_els}")
    except Exception as e:
        log.debug(f"{tag}aria-label query failed: {e}")

    try:
        roles: list[dict] = page.evaluate("""
            () => [...document.querySelectorAll('[role]')].map(el => ({
                tag: el.tagName,
                role: el.getAttribute('role'),
                id: el.id,
                testid: el.getAttribute('data-testid') || ''
            }))
        """)
        log.debug(f"{tag}role= elements: {roles}")
    except Exception as e:
        log.debug(f"{tag}role= query failed: {e}")

    # Dump structure of every modal-like container (strip base64 to keep log readable)
    MODAL_CANDIDATES = [
        '[role="dialog"]',
        '[aria-modal="true"]',
        '[data-testid*="modal"]',
        '[data-testid*="overlay"]',
        '[data-testid*="popup"]',
    ]
    for sel in MODAL_CANDIDATES:
        try:
            els = page.query_selector_all(sel)
            for idx, el in enumerate(els):
                html: str = el.evaluate("el => el.outerHTML")
                # Strip base64 blobs so the log stays readable
                html = re.sub(
                    r'data:image/[^;]+;base64,[A-Za-z0-9+/=]+',
                    '[base64-data]',
                    html,
                )
                log.debug(
                    f"{tag}modal candidate {sel!r} [{idx}] "
                    f"({len(html)} chars):\n{html[:3000]}"
                )
        except Exception as e:
            log.debug(f"{tag}modal candidate {sel!r} query failed: {e}")


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
    log.info("═══ Delhaize ═══")
    ctx = _launch_browser(pw)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    page.goto("https://www.delhaize.be/nl/my-account/loyalty/tickets", wait_until="domcontentloaded")
    log.info("→ Browser opened. Please log in if needed.")
    log.info("→ Waiting for receipts to appear …")

    # Wait for at least one receipt row (up to 5 minutes for login)
    try:
        page.wait_for_selector('[data-testid="my-receipts-list-row"]', timeout=300_000)
    except Exception:
        log.error("Timed out waiting for receipts page. Did you log in?")
        _dom_snapshot(page, "timeout")
        ctx.close()
        return

    # Log the page structure once after login — helps detect site changes
    log.debug("Taking post-login DOM snapshot …")
    _dom_snapshot(page, "post-login")

    # Expand all collapsed months
    log.info("Expanding all months …")
    toggles = page.query_selector_all(
        '[data-testid="collapsable-button-toggle"][aria-expanded="false"]'
    )
    log.debug(f"Found {len(toggles)} collapsed month toggles")
    for toggle in toggles:
        toggle.scroll_into_view_if_needed()
        toggle.click()
        page.wait_for_timeout(800)
    page.wait_for_timeout(1500)

    # Re-query rows AFTER expanding (DOM may have changed)
    rows = page.query_selector_all('[data-testid="my-receipts-list-row"]')
    log.info(f"Found {len(rows)} receipts")

    # Timings mirrored from the working scrape_delhaize_tickets.js
    MODAL_OPEN_WAIT  = 1500   # ms to let image load after clicking receipt
    MODAL_CLOSE_WAIT = 1000   # ms after clicking close before next receipt

    CLOSE_SELECTORS = [
        '[aria-label*="Sluit"]',
        '[aria-label*="Close"]',
        '[aria-label*="sluiten"]',
        '[role="dialog"] button',
        'button.close',
        '.modal-close',
    ]
    IMAGE_SELECTORS = [
        'img[src^="data:image/jpeg;base64"]',
        'img[src^="data:image/png;base64"]',
        'div[data-testid="modal-main-content"] img',
        'img[alt*="Kasticket" i]',
        'img[alt*="kassaticket" i]',
        'img[alt*="ticket" i]',
        '[role="dialog"] img[src^="data:image"]',
    ]

    def _close_modal(label: str = ""):
        """Close the modal using the same selector order as the working JS scraper."""
        close = _try_selectors(page, CLOSE_SELECTORS, f"{label}/close")
        if close:
            close.click()
        else:
            log.warning(f"[{label}] No close button found — pressing Escape")
            page.keyboard.press("Escape")
        page.wait_for_timeout(MODAL_CLOSE_WAIT)

    saved = 0
    for i in range(len(rows)):
        # Re-query rows each iteration to avoid stale element references
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
            log.info(f"[{i+1}/{len(rows)}] Already saved {img_path.name}, skipping")
            continue

        btn = row.query_selector('[data-testid="my-receipts-list-button"]')
        if not btn:
            log.warning(f"[{i+1}/{len(rows)}] No button for {date_text}, skipping")
            continue

        btn.scroll_into_view_if_needed()
        btn.click()
        log.debug(f"[{date_text}] Clicked receipt button, waiting {MODAL_OPEN_WAIT} ms …")
        page.wait_for_timeout(MODAL_OPEN_WAIT)

        # Snapshot the DOM after the modal should have opened — goes to log file.
        # This reveals the exact selectors available, helping simplify the
        # fallback chains once a stable selector is confirmed.
        _dom_snapshot(page, date_text)

        # Query image globally — same priority order as the working JS scraper
        img = _try_selectors(page, IMAGE_SELECTORS, f"{date_text}/image")

        if img:
            src = img.get_attribute("src") or ""
            if src.startswith("data:image"):
                import base64 as _b64
                b64 = src.split(",", 1)[1] if "," in src else src
                img_path.write_bytes(_b64.b64decode(b64))
                log.info(f"[{i+1}/{len(rows)}] Saved {img_path.name}")
                saved += 1
            else:
                log.warning(f"[{i+1}/{len(rows)}] Image src not base64 for {date_text} (src[:80]: {src[:80]!r})")
        else:
            log.warning(f"[{i+1}/{len(rows)}] No image found for {date_text} — modal too slow or structure changed")

        _close_modal(label=date_text)

    log.info(f"Done — saved {saved} new receipt images")
    log.info(f"Full debug log written to {LOG_FILE}")
    ctx.close()


# ── Carrefour ────────────────────────────────────────────────────────────────

def scrape_carrefour(pw) -> None:
    """
    Navigate to Carrefour Frequently Purchased page.
    Wait for login, then scrape product names + brands.
    """
    log.info("═══ Carrefour ═══")
    ctx = _launch_browser(pw)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    page.goto("https://www.carrefour.be/nl/frequentlypurchased", wait_until="domcontentloaded")
    log.info("→ Browser opened. Please log in if needed.")
    log.info("→ Waiting for product tiles …")

    try:
        page.wait_for_selector(".product-tile", timeout=300_000)
    except Exception:
        log.error("Timed out. Did you log in and navigate to the page?")
        _dom_snapshot(page, "carrefour-timeout")
        ctx.close()
        return

    log.debug("Taking post-login DOM snapshot for Carrefour …")
    _dom_snapshot(page, "carrefour-post-login")

    # Scroll down to load all products
    log.info("Scrolling to load all products …")
    prev_count = 0
    for _ in range(50):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(800)
        tiles = page.query_selector_all(".product-tile")
        if len(tiles) == prev_count:
            break
        prev_count = len(tiles)

    tiles = page.query_selector_all(".product-tile")
    log.info(f"Found {len(tiles)} product tiles")

    # Log which name/brand selectors actually matched on the first tile
    if tiles:
        first = tiles[0]
        _try_selectors(first, ["span.d-lg-none.mobile-name", "span[class*=mobile]", "span[class*=name]", ".product-name"], "carrefour/name")
        _try_selectors(first, [".brand-wrapper a", ".brand a", "[class*=brand]"], "carrefour/brand")

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

    log.info(f"Saved {len(items)} items → {out_path}")
    ctx.close()


# ── Colruyt ──────────────────────────────────────────────────────────────────

def scrape_colruyt(pw) -> None:
    """
    Navigate to Colruyt My Products / favorites page.
    Wait for login, then scrape product cards.
    """
    log.info("═══ Colruyt ═══")
    ctx = _launch_browser(pw)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    page.goto("https://www.colruyt.be/nl/mijn-boodschappen/favorieten", wait_until="domcontentloaded")
    log.info("→ Browser opened. Please log in if needed.")
    log.info("→ Waiting for product cards …")

    CARD_SELECTORS = ["a.card.card--article", ".product-card", ".favorite-item"]
    try:
        page.wait_for_selector(", ".join(CARD_SELECTORS), timeout=300_000)
    except Exception:
        log.error("Timed out. Did you log in?")
        _dom_snapshot(page, "colruyt-timeout")
        ctx.close()
        return

    log.debug("Taking post-login DOM snapshot for Colruyt …")
    _dom_snapshot(page, "colruyt-post-login")

    # Scroll to load all
    log.info("Scrolling to load all products …")
    prev_count = 0
    for _ in range(50):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(800)
        cards = page.query_selector_all(", ".join(CARD_SELECTORS))
        if len(cards) == prev_count:
            break
        prev_count = len(cards)

    cards = page.query_selector_all(", ".join(CARD_SELECTORS))
    log.info(f"Found {len(cards)} product cards")

    # Log which sub-selectors matched on the first card
    if cards:
        first = cards[0]
        _try_selectors(first, [".card__text", ".product-name", "[class*=name]", "h3", "h2"], "colruyt/name")
        _try_selectors(first, [".card__quantity", ".product-weight", "[class*=quantity]", "[class*=weight]"], "colruyt/weight")

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

    log.info(f"Saved {len(items)} items → {out_path}")
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
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Print DEBUG-level messages to the console (always written to scraper.log)",
    )
    args = parser.parse_args()
    _setup_logging(verbose=args.verbose)
    log.info(f"Logging to {LOG_FILE}")

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
                log.exception(f"{store} failed: {e}")

    log.info("\nAll done. Run the nutrient analysis pipeline next:")
    log.info("  cd nutrient_analysis && python 01_build_mapping.py && python 02_nutrition_report.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
