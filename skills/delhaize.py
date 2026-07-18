#!/usr/bin/env python3
"""
skills.delhaize — Delhaize receipt image scraper
================================================

Pulls kasticket / receipt images from Delhaize "My Receipts" into
``data/delhaize/<yyyy>_<mm>_<dd>.jpg`` (same-day extras: ``_b``, ``_c``, …).

────────────────────────────────────────────────────────────────────────
AGENT INSTRUCTIONS (read this first)
────────────────────────────────────────────────────────────────────────
1. Default command (preferred — uses the user's Google Chrome login)::

       python -m skills.delhaize

2. Do **not** pass ``--no-chrome`` unless the user asks. That opens a blank
   Playwright profile and forces a fresh Delhaize login.

3. Tell the user once, before / as it starts:
   - Chrome may **quit briefly**, then reopen in a debug window that reuses
     their Delhaize cookies (Chrome 136+ blocks CDP on the real profile, so
     we sync cookies into ``.chrome_debug_profile/``).
   - If the tickets page asks them to log in, they should do that in the
     opened window (up to 5 minutes).

4. Watch the terminal for:
   - ``done — saved N new images`` → success
   - ``STUCK`` / observe mode → ask the user to finish the failing step in
     the browser, then use the saved ``data/sessions/observe_*.json``

5. After a successful scrape, next pipeline step::

       python -m skills.ocr_batch

6. One-time deps if missing::

       pip install playwright && playwright install chromium

────────────────────────────────────────────────────────────────────────
Human usage
────────────────────────────────────────────────────────────────────────
    python -m skills.delhaize                 # Chrome cookies (default)
    python -m skills.delhaize --chrome-profile "Profile 1"
    python -m skills.delhaize --no-chrome     # isolated profile (re-login)
    python -m skills.delhaize --cdp http://127.0.0.1:9222

If Chrome is already running with remote debugging on the CDP port, the
scraper attaches without quitting.
"""

from __future__ import annotations

import argparse
import base64
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from .common import DELHAIZE_DATA_DIR, ROOT_DIR

DATA_DIR = DELHAIZE_DATA_DIR
PROFILE_DIR = ROOT_DIR / ".browser_profile"
CHROME_DEBUG_PROFILE = ROOT_DIR / ".chrome_debug_profile"
CDP_ENDPOINT = "http://127.0.0.1:9222"
TICKETS_URL = "https://www.delhaize.be/nl/my-account/loyalty/tickets"

DATA_DIR.mkdir(parents=True, exist_ok=True)
PROFILE_DIR.mkdir(exist_ok=True)

FAILURE_THRESHOLD = 3
MODAL_CLOSE_WAIT = 1000  # ms

# NL + FR month accordion headers on the tickets page
_MONTH_BTN_RE = re.compile(
    r"^("
    r"januari|februari|maart|april|mei|juni|juli|augustus|"
    r"september|oktober|november|december|"
    r"janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|"
    r"septembre|octobre|novembre|décembre|decembre"
    r")\s+\d{4}$",
    re.I,
)

IMG_SELECTORS = [
    'img[src^="data:image/jpeg;base64"]',
    'img[src^="data:image/png;base64"]',
    'div[data-testid="modal-main-content"] img',
    'img[alt*="Kasticket" i]',
    'img[alt*="kassaticket" i]',
    'img[alt*="ticket" i]',
    '[role="dialog"] img[src^="data:image"]',
]

_t0 = time.time()


def _log(msg: str) -> None:
    print(f"  [{time.time() - _t0:6.1f}s] {msg}", flush=True)


def _chrome_paths() -> tuple[Path | None, Path | None]:
    """Return (chrome_binary, user_data_dir) for this OS, or (None, None)."""
    system = platform.system()
    home = Path.home()
    if system == "Darwin":
        binary = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        user_data = home / "Library/Application Support/Google/Chrome"
    elif system == "Linux":
        binary = Path("/usr/bin/google-chrome")
        if not binary.exists():
            binary = Path("/usr/bin/google-chrome-stable")
        user_data = home / ".config/google-chrome"
    elif system == "Windows":
        local = Path.home() / "AppData/Local/Google/Chrome/Application/chrome.exe"
        binary = local if local.exists() else Path(
            r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        )
        user_data = home / "AppData/Local/Google/Chrome/User Data"
    else:
        return None, None
    return (binary if binary.exists() else None), (user_data if user_data.exists() else None)


def _resolve_chrome_profile(user_data: Path, preferred: str | None) -> Path:
    """Pick a Chrome profile directory that likely has login cookies."""
    if preferred:
        path = user_data / preferred
        if not path.is_dir():
            raise FileNotFoundError(
                f"Chrome profile {preferred!r} not found under {user_data}"
            )
        return path

    candidates: list[Path] = []
    default = user_data / "Default"
    if default.is_dir():
        candidates.append(default)
    candidates.extend(sorted(user_data.glob("Profile *")))

    def _cookie_mtime(p: Path) -> float:
        cookies = p / "Cookies"
        return cookies.stat().st_mtime if cookies.exists() else 0.0

    if not candidates:
        raise FileNotFoundError(f"No Chrome profiles found under {user_data}")
    return max(candidates, key=_cookie_mtime)


def _cdp_available(endpoint: str = CDP_ENDPOINT) -> bool:
    try:
        with urllib.request.urlopen(endpoint + "/json/version", timeout=1.5) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _chrome_running() -> bool:
    system = platform.system()
    if system == "Darwin":
        return subprocess.run(["pgrep", "-x", "Google Chrome"], capture_output=True).returncode == 0
    if system == "Linux":
        return subprocess.run(["pgrep", "-f", "google-chrome"], capture_output=True).returncode == 0
    if system == "Windows":
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq chrome.exe"],
            capture_output=True,
            text=True,
        )
        return "chrome.exe" in (out.stdout or "").lower()
    return False


def _quit_chrome() -> None:
    """Quit running Google Chrome so we can copy its cookies safely."""
    _log("quitting Google Chrome so we can sync your login cookies …")
    system = platform.system()
    if system == "Darwin":
        subprocess.run(
            ["osascript", "-e", 'tell application "Google Chrome" to quit'],
            check=False,
            capture_output=True,
        )
    elif system == "Linux":
        subprocess.run(["pkill", "-f", "google-chrome"], check=False, capture_output=True)
    elif system == "Windows":
        subprocess.run(["taskkill", "/IM", "chrome.exe", "/F"], check=False, capture_output=True)

    for _ in range(40):
        if not _chrome_running():
            time.sleep(1.0)
            return
        time.sleep(0.5)
    _log("Chrome still running — continuing anyway")


def _prepare_chrome_debug_profile(chrome_profile: str | None = None) -> Path:
    """Clone login state into a debug dir Playwright can control.

    Chrome 136+ refuses ``--remote-debugging-port`` on the real user-data-dir,
    so we copy cookies/session into ``.chrome_debug_profile/``.
    """
    _, user_data = _chrome_paths()
    if user_data is None:
        raise FileNotFoundError("Google Chrome user-data directory not found")

    src = _resolve_chrome_profile(user_data, chrome_profile)
    dst_root = CHROME_DEBUG_PROFILE
    dst = dst_root / "Default"
    dst_root.mkdir(parents=True, exist_ok=True)
    dst.mkdir(parents=True, exist_ok=True)

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
    _log(f"syncing login from Chrome profile {src.name!r} → {dst_root}")
    for name in names:
        s = src / name
        d = dst / name
        if not s.exists():
            continue
        try:
            if s.is_dir():
                if d.exists():
                    shutil.rmtree(d)
                shutil.copytree(s, d)
            else:
                d.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(s, d)
        except OSError as e:
            _log(f"  skip {name}: {e}")

    for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        lock = dst_root / name
        if lock.exists() or lock.is_symlink():
            lock.unlink(missing_ok=True)
    return dst_root


def _start_chrome_with_cdp(
    cdp: str = CDP_ENDPOINT,
    *,
    chrome_profile: str | None = None,
) -> subprocess.Popen | None:
    """Start Chrome with remote debugging on a cookie-synced debug profile."""
    chrome_bin, user_data = _chrome_paths()
    if chrome_bin is None or user_data is None:
        _log("Google Chrome not found on this machine")
        return None

    port = cdp.rsplit(":", 1)[-1]
    user_data_dir = _prepare_chrome_debug_profile(chrome_profile)
    _log(f"starting Google Chrome with --remote-debugging-port={port}")
    proc = subprocess.Popen(
        [
            str(chrome_bin),
            f"--remote-debugging-port={port}",
            f"--user-data-dir={user_data_dir}",
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


def _launch_browser(
    pw,
    *,
    use_chrome: bool = True,
    cdp: str = CDP_ENDPOINT,
    chrome_profile: str | None = None,
):
    """Return ``(context, browser_or_none, owns_context)``.

    Chrome path (default):
      1. Attach if CDP is already listening
      2. Else quit Chrome if needed, sync cookies → ``.chrome_debug_profile``,
         relaunch with ``--remote-debugging-port``
    Fallback: isolated Playwright profile under ``.browser_profile/``
    """
    if use_chrome:
        if not _cdp_available(cdp):
            if _chrome_running():
                print(
                    "  → Chrome is open — quitting briefly to sync your Delhaize login,\n"
                    "    then reopening a debug window (your normal tabs will close).",
                    flush=True,
                )
                _quit_chrome()
            else:
                print(
                    "  → Opening Chrome with your synced Delhaize login cookies …",
                    flush=True,
                )
            try:
                _start_chrome_with_cdp(cdp, chrome_profile=chrome_profile)
            except FileNotFoundError as e:
                _log(f"Chrome profile sync failed: {e}")

        if _cdp_available(cdp):
            _log(f"attaching to Chrome via CDP ({cdp})")
            browser = pw.chromium.connect_over_cdp(cdp)
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            return ctx, browser, False

        _log("Could not attach to Chrome CDP — falling back to isolated profile")
        print(
            "  → Tip: log into Delhaize in the window that opens; next run can use --chrome\n"
            "    once Google Chrome is installed and you have logged in there once.",
            flush=True,
        )

    _log(f"launching isolated Chromium profile: {PROFILE_DIR}")
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=False,
        viewport={"width": 1280, "height": 900},
        args=["--disable-blink-features=AutomationControlled"],
    )
    return ctx, None, True


def _expand_all_months(page) -> int:
    """Expand every month accordion and scroll until row count stabilizes."""
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

        count = len(page.query_selector_all('[data-testid="my-receipts-list-row"]'))
        if count != prev_count or clicked:
            _log(
                f"  load round {round_i + 1}: {count} receipts "
                f"({clicked} month(s) expanded)"
            )
            prev_count = count
            continue
        if round_i > 0:
            _log(f"receipt list stable at {count}")
            break
    return len(page.query_selector_all('[data-testid="my-receipts-list-row"]'))


def _close_modal(page) -> None:
    close = (
        page.query_selector('[aria-label*="Sluit"]')
        or page.query_selector('[aria-label*="Close"]')
        or page.query_selector('[aria-label*="Fermer"]')
        or page.query_selector('[aria-label*="sluiten"]')
        or page.query_selector('[role="dialog"] button')
        or page.query_selector("button.close, .modal-close")
    )
    if close:
        lbl = close.get_attribute("aria-label") or close.tag_name or "?"
        _log(f"  close modal ← [{lbl}]")
        try:
            close.click(force=True)
        except Exception:
            page.keyboard.press("Escape")
    else:
        _log("  close modal ← Escape (no close button found)")
        page.keyboard.press("Escape")
    page.wait_for_timeout(MODAL_CLOSE_WAIT)


def _save_ticket_image(page, img_path: Path) -> bool:
    """Wait for modal ticket image and write it to img_path. Return True on success."""
    img = None
    matched_sel = None
    deadline = time.time() + 12.0
    while time.time() < deadline and img is None:
        for sel in IMG_SELECTORS:
            candidate = page.query_selector(sel)
            if not candidate:
                continue
            src0 = candidate.get_attribute("src") or ""
            if src0.startswith("data:image") or src0.startswith("http"):
                img = candidate
                matched_sel = sel
                break
        if img is None:
            page.wait_for_timeout(300)

    if not img:
        return False

    _log(f"    image found via: {matched_sel}")
    src = img.get_attribute("src") or ""
    if src.startswith("data:image"):
        b64 = src.split(",", 1)[1] if "," in src else src
        img_path.write_bytes(base64.b64decode(b64))
        return True
    if src.startswith("http"):
        data = page.evaluate(
            """async (url) => {
                const r = await fetch(url);
                const buf = await r.arrayBuffer();
                return Array.from(new Uint8Array(buf));
            }""",
            src,
        )
        img_path.write_bytes(bytes(data))
        return True
    return False


def scrape_delhaize(
    pw,
    *,
    use_chrome: bool = True,
    cdp: str = CDP_ENDPOINT,
    chrome_profile: str | None = None,
) -> None:
    from .observe import observe_mode

    print("═══ Delhaize ═══")
    print(f"  Output: {DATA_DIR}")
    ctx, browser, owns_context = _launch_browser(
        pw, use_chrome=use_chrome, cdp=cdp, chrome_profile=chrome_profile
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    page.goto(TICKETS_URL, wait_until="domcontentloaded")
    if use_chrome:
        print("  → Using your Chrome login (cookie-synced debug profile).")
    else:
        print("  → Isolated browser profile (log in if prompted).")
    print("  → Please log in if the receipts list does not appear.")
    _log("waiting for [data-testid=my-receipts-list-row] (up to 5 min) …")

    try:
        page.wait_for_selector('[data-testid="my-receipts-list-row"]', timeout=300_000)
    except Exception:
        _log("✗ Timed out — switching to observe mode")
        observe_mode(page, ctx, "receipts page never appeared")
        return

    n_rows = _expand_all_months(page)
    rows = page.query_selector_all('[data-testid="my-receipts-list-row"]')
    _log(f"found {len(rows)} receipts" + ("" if len(rows) == n_rows else f" (was {n_rows})"))

    saved = 0
    consecutive_failures = 0
    date_seen: dict[str, int] = {}

    for i in range(len(rows)):
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
            _log(f"[{i + 1}/{len(rows)}] no date element — skipping row")
            consecutive_failures += 1
            continue
        date_text = date_el.text_content().strip()
        parts = date_text.split("/")
        if len(parts) != 3:
            _log(f"[{i + 1}/{len(rows)}] unexpected date format: {date_text!r}")
            consecutive_failures += 1
            continue
        dd, mm, yyyy = parts
        base = f"{yyyy}_{mm}_{dd}"
        occ = date_seen.get(base, 0)
        date_seen[base] = occ + 1
        img_path = (
            DATA_DIR / f"{base}.jpg"
            if occ == 0
            else DATA_DIR / f"{base}_{chr(ord('a') + occ)}.jpg"
        )

        if img_path.exists():
            _log(f"[{i + 1}/{len(rows)}] {img_path.name} already exists, skipping")
            consecutive_failures = 0
            continue

        btn = row.query_selector('[data-testid="my-receipts-list-button"]')
        if not btn:
            _log(f"[{i + 1}/{len(rows)}] no button for {date_text}")
            consecutive_failures += 1
            continue

        _log(f"[{i + 1}/{len(rows)}] {date_text} — clicking receipt")
        btn.scroll_into_view_if_needed()
        btn.click()
        _log(f"[{i + 1}/{len(rows)}] waiting for ticket image …")

        try:
            ok = _save_ticket_image(page, img_path)
        except Exception as e:
            _log(f"[{i + 1}/{len(rows)}] ✗ save failed: {e}")
            ok = False

        if ok:
            _log(f"[{i + 1}/{len(rows)}] ✓ saved {img_path.name}")
            saved += 1
            consecutive_failures = 0
        else:
            _log(f"[{i + 1}/{len(rows)}] ✗ no image matched any selector")
            consecutive_failures += 1

        _close_modal(page)

    _log(f"done — saved {saved} new images to {DATA_DIR}")
    if owns_context:
        ctx.close()
    elif browser is not None:
        _log("left your Chrome session open")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scrape Delhaize receipt ticket images using your Chrome login",
        epilog=(
            "Agents: run with defaults (Chrome on). "
            "Next step after success: python -m skills.ocr_batch"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--chrome",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use Google Chrome login cookies via a synced debug profile (default: on)",
    )
    parser.add_argument(
        "--chrome-profile",
        default=None,
        metavar="NAME",
        help='Chrome profile folder name (default: newest Cookies among Default / "Profile N")',
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
        print(
            "Playwright not installed. Run once:\n"
            "  pip install playwright && playwright install chromium",
            file=sys.stderr,
        )
        return 1

    if args.chrome:
        binary, user_data = _chrome_paths()
        if binary is None or user_data is None:
            print(
                "Google Chrome not found — will fall back to an isolated browser.\n"
                "Install Chrome and log into delhaize.be once for cookie reuse,\n"
                "or continue and log in manually in the window that opens.",
                flush=True,
            )

    with sync_playwright() as pw:
        scrape_delhaize(
            pw,
            use_chrome=args.chrome,
            cdp=args.cdp,
            chrome_profile=args.chrome_profile,
        )

    print("\nNext: OCR the ticket images:")
    print("  python -m skills.ocr_batch")
    return 0


if __name__ == "__main__":
    sys.exit(main())
