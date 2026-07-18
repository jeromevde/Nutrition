#!/usr/bin/env python3
"""
skills.delhaize — Delhaize receipt image scraper
==========================================================
Opens the Delhaize "My Receipts" page in a real browser, waits for login,
then iterates every receipt and saves the ticket image as a .jpg.

If the scraper gets stuck (3+ consecutive failures to extract an image),
it automatically switches to OBSERVE MODE: records your manual actions in
the browser and saves a session JSON you can feed to an LLM to fix it.

Usage:
    pip install playwright && playwright install chromium
    python -m skills.delhaize              # uses your real Chrome profile (default)
    python -m skills.delhaize --no-chrome  # isolated Playwright profile

Note: using --chrome will quit/relaunch Google Chrome so Playwright can
reuse your logged-in cookies. Or start Chrome yourself with:
  open -a "Google Chrome" --args --remote-debugging-port=9222
and the scraper will attach without quitting."""

from __future__ import annotations
import argparse
import base64
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from .common import DELHAIZE_DATA_DIR, ROOT_DIR

DATA_DIR     = DELHAIZE_DATA_DIR
PROFILE_DIR  = ROOT_DIR / ".browser_profile"
CHROME_USER_DATA = Path.home() / "Library/Application Support/Google/Chrome"
CHROME_DEBUG_PROFILE = ROOT_DIR / ".chrome_debug_profile"
CDP_ENDPOINT = "http://127.0.0.1:9222"
DATA_DIR.mkdir(parents=True, exist_ok=True)
PROFILE_DIR.mkdir(exist_ok=True)

# How many consecutive receipt failures before we give up and go observe mode
FAILURE_THRESHOLD = 3
MODAL_OPEN_WAIT   = 1500   # ms after clicking receipt
MODAL_CLOSE_WAIT  = 1000   # ms after closing modal

# Dutch month accordion headers on the tickets page
_MONTH_BTN_RE = re.compile(
    r"^(januari|februari|maart|april|mei|juni|juli|augustus|"
    r"september|oktober|november|december)\s+\d{4}$",
    re.I,
)
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


def _cdp_available(endpoint: str = CDP_ENDPOINT) -> bool:
    try:
        with urllib.request.urlopen(endpoint + "/json/version", timeout=1.5) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _quit_chrome() -> None:
    """Quit running Google Chrome so we can attach to its profile."""
    _log("quitting Google Chrome so we can reuse your logged-in profile …")
    subprocess.run(
        ["osascript", "-e", 'tell application "Google Chrome" to quit'],
        check=False,
        capture_output=True,
    )
    # Wait until the profile lock is released
    for _ in range(40):
        running = subprocess.run(["pgrep", "-x", "Google Chrome"], capture_output=True)
        if running.returncode != 0:
            time.sleep(1.0)
            return
        time.sleep(0.5)
    _log("Chrome still running — continuing anyway")


def _prepare_chrome_debug_profile() -> Path:
    """Clone the Default Chrome profile into a debug dir.

    Chrome 136+ refuses --remote-debugging-port on the real user-data-dir, so we
    copy cookies/login state into a dedicated profile Playwright can control.
    """
    src = CHROME_USER_DATA / "Default"
    dst_root = CHROME_DEBUG_PROFILE
    dst = dst_root / "Default"
    dst_root.mkdir(parents=True, exist_ok=True)
    dst.mkdir(parents=True, exist_ok=True)

    # Auth + session bits (keep this lean; full profile copy is huge/slow)
    names = [
        "Cookies",
        "Cookies-journal",
        "Login Data",
        "Login Data-journal",
        "Login Data For Account",
        "Web Data",
        "Web Data-journal",
        "Preferences",
        "Secure Preferences",
        "Local Storage",
        "Session Storage",
        "Network",
        "IndexedDB",
    ]
    _log(f"syncing login cookies into debug profile: {dst_root}")
    for name in names:
        s = src / name
        d = dst / name
        if not s.exists():
            continue
        if s.is_dir():
            subprocess.run(["rsync", "-a", f"{s}/", f"{d}/"], check=False)
        else:
            d.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["cp", "-p", str(s), str(d)], check=False)

    # Clear locks in the debug profile
    for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        lock = dst_root / name
        if lock.exists() or lock.is_symlink():
            lock.unlink(missing_ok=True)
    return dst_root


def _start_chrome_with_cdp(cdp: str = CDP_ENDPOINT) -> subprocess.Popen | None:
    """Start system Chrome with remote debugging on a cloned logged-in profile."""
    port = cdp.rsplit(":", 1)[-1]
    chrome_bin = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if not Path(chrome_bin).exists():
        return None
    if not CHROME_USER_DATA.exists():
        return None

    user_data = _prepare_chrome_debug_profile()
    _log(f"starting Google Chrome with --remote-debugging-port={port}")
    proc = subprocess.Popen(
        [
            chrome_bin,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={user_data}",
            "--profile-directory=Default",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for i in range(60):
        if _cdp_available(cdp):
            _log(f"Chrome CDP ready after {i + 1}s")
            return proc
        time.sleep(1.0)
    _log("Chrome started but CDP never became ready")
    return proc


def _launch_browser(pw, *, use_chrome: bool = True, cdp: str = CDP_ENDPOINT):
    """Return (context, browser_or_none, owns_context).

    Prefer your real Chrome login cookies via a debug-profile clone + CDP:
      1. Connect over CDP if already available
      2. Otherwise quit Chrome, clone cookies into .chrome_debug_profile, relaunch
    Fallback: isolated Playwright profile under .browser_profile/
    """
    if use_chrome:
        if not _cdp_available(cdp):
            chrome_running = subprocess.run(
                ["pgrep", "-x", "Google Chrome"], capture_output=True
            ).returncode == 0
            if chrome_running:
                _quit_chrome()
            _start_chrome_with_cdp(cdp)

        if _cdp_available(cdp):
            _log(f"attaching to Chrome via CDP ({cdp})")
            browser = pw.chromium.connect_over_cdp(cdp)
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            return ctx, browser, False

        _log("Could not attach to Chrome CDP — falling back to isolated profile")

    _log(f"launching isolated Chromium profile: {PROFILE_DIR}")
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=False,
        viewport={"width": 1280, "height": 900},
        args=["--disable-blink-features=AutomationControlled"],
    )
    return ctx, None, True

def scrape_delhaize(pw, *, use_chrome: bool = True, cdp: str = CDP_ENDPOINT) -> None:
    from .observe import observe_mode

    print("═══ Delhaize ═══")
    ctx, browser, owns_context = _launch_browser(pw, use_chrome=use_chrome, cdp=cdp)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    page.goto(
        "https://www.delhaize.be/nl/my-account/loyalty/tickets",
        wait_until="domcontentloaded",
    )
    print("  → Browser opened (your Chrome profile)." if use_chrome else "  → Browser opened.")
    print("  → Please log in if needed.")
    _log("waiting for [data-testid=my-receipts-list-row] (up to 5 min) …")

    try:
        page.wait_for_selector('[data-testid="my-receipts-list-row"]', timeout=300_000)
    except Exception:
        _log("✗ Timed out — switching to observe mode")
        observe_mode(page, ctx, "receipts page never appeared")
        return

    # Expand months + scroll until the list stops growing (lazy-loaded history).
    # Month headers are plain buttons with aria-expanded (testid removed).
    _log("expanding months and scrolling to load all receipts …")
    prev_count = -1
    for round_i in range(80):
        clicked = 0
        for toggle in page.query_selector_all('button[aria-expanded="false"]'):
            try:
                label = (toggle.inner_text() or "").strip()
                if not _MONTH_BTN_RE.match(label):
                    continue
                toggle.scroll_into_view_if_needed()
                toggle.click()
                clicked += 1
                page.wait_for_timeout(350)
            except Exception:
                pass

        page.evaluate(
            """() => {
                const el = document.scrollingElement || document.documentElement;
                el.scrollTop = el.scrollHeight;
                window.scrollTo(0, document.body.scrollHeight);
            }"""
        )
        page.wait_for_timeout(700)

        rows = page.query_selector_all('[data-testid="my-receipts-list-row"]')
        count = len(rows)
        if count != prev_count or clicked:
            _log(f"  load round {round_i + 1}: {count} receipts "
                 f"({clicked} month(s) expanded)")
            prev_count = count
            continue
        if round_i > 0:
            _log(f"receipt list stable at {count}")
            break

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
    date_seen: dict[str, int] = {}

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
        base = f"{yyyy}_{mm}_{dd}"
        # Same-day duplicates → base.jpg, base_b.jpg, base_c.jpg, …
        occ = date_seen.get(base, 0)
        date_seen[base] = occ + 1
        img_path = (
            DATA_DIR / f"{base}.jpg"
            if occ == 0
            else DATA_DIR / f"{base}_{chr(ord('a') + occ)}.jpg"
        )

        if img_path.exists():
            _log(f"[{i+1}/{len(rows)}] {img_path.name} already exists, skipping")
            consecutive_failures = 0
            continue

        btn = row.query_selector('[data-testid="my-receipts-list-button"]')
        if not btn:
            _log(f"[{i+1}/{len(rows)}] no button for {date_text}")
            consecutive_failures += 1
            continue

        _log(f"[{i+1}/{len(rows)}] {date_text} — clicking receipt")
        btn.scroll_into_view_if_needed()
        btn.click()
        _log(f"[{i+1}/{len(rows)}] waiting for ticket image …")

        img = None
        matched_sel = None
        deadline = time.time() + 12.0
        while time.time() < deadline and img is None:
            for sel in IMG_SELECTORS:
                candidate = page.query_selector(sel)
                if candidate:
                    src0 = candidate.get_attribute("src") or ""
                    if src0.startswith("data:image") or src0.startswith("http"):
                        img = candidate
                        matched_sel = sel
                        break
            if img is None:
                page.wait_for_timeout(300)

        if not img:
            _log(f"[{i+1}/{len(rows)}] ✗ no image matched any selector")
            consecutive_failures += 1
            _close_modal()
            continue

        _log(f"[{i+1}/{len(rows)}] image found via: {matched_sel}")
        src = img.get_attribute("src") or ""
        if src.startswith("data:image"):
            b64 = src.split(",", 1)[1] if "," in src else src
            img_path.write_bytes(base64.b64decode(b64))
            _log(f"[{i+1}/{len(rows)}] ✓ saved {img_path.name}")
            saved += 1
            consecutive_failures = 0
        elif src.startswith("http"):
            try:
                data = page.evaluate(
                    """async (url) => {
                        const r = await fetch(url);
                        const buf = await r.arrayBuffer();
                        return Array.from(new Uint8Array(buf));
                    }""",
                    src,
                )
                img_path.write_bytes(bytes(data))
                _log(f"[{i+1}/{len(rows)}] ✓ saved {img_path.name} (url)")
                saved += 1
                consecutive_failures = 0
            except Exception as e:
                _log(f"[{i+1}/{len(rows)}] ✗ failed to fetch image url: {e}")
                consecutive_failures += 1
        else:
            _log(f"[{i+1}/{len(rows)}] image src is not usable for {date_text}: {src[:80]!r}")
            consecutive_failures += 1

        _close_modal()

    _log(f"done — saved {saved} new images to {DATA_DIR}")
    # Only close a browser we launched. Leave your normal Chrome running if attached via CDP.
    if owns_context:
        ctx.close()
    elif browser is not None:
        _log("left your Chrome session open")


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape Delhaize receipt ticket images")
    parser.add_argument(
        "--chrome",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use your real Google Chrome profile/cookies (default: on). "
             "If Chrome is open, it will be quit and relaunched with the same profile.",
    )
    parser.add_argument(
        "--cdp",
        default=CDP_ENDPOINT,
        help=f"Chrome DevTools endpoint (default: {CDP_ENDPOINT})",
    )
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright not installed:\n  pip install playwright && playwright install chromium")
        return 1

    with sync_playwright() as pw:
        scrape_delhaize(pw, use_chrome=args.chrome, cdp=args.cdp)

    print("\nNext: OCR the ticket images:")
    print("  python -m skills.ocr_batch")
    return 0


if __name__ == "__main__":
    sys.exit(main())
