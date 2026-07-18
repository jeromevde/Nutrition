"""Capture Carrefour and Colruyt digital receipts from an Android emulator.

The retailer apps stay inside the emulator. This module only opens their Google
Play pages, launches them for an interactive sign-in, and saves receipt screens
that the signed-in user has opened. It never reads or stores credentials.

Usage:
    python -m skills.mobile_receipts setup
    python -m skills.mobile_receipts start
    python -m skills.mobile_receipts install
    python -m skills.mobile_receipts login carrefour
    python -m skills.mobile_receipts capture carrefour 2026-07-18 --pages 3
"""

from __future__ import annotations

import argparse
import os
import subprocess
import time
from datetime import date
from pathlib import Path

from .common import CARREFOUR_DATA_DIR, COLRUYT_DATA_DIR

SDK_ROOT = Path("/opt/homebrew/share/android-commandlinetools")
AVD_NAME = "nutrition-receipts"
SYSTEM_IMAGE = "system-images;android-36;google_apis_playstore;arm64-v8a"
RETAILERS = {
    "carrefour": ("be.carrefour.singleapp", CARREFOUR_DATA_DIR),
    "colruyt": ("be.colruyt.xtra", COLRUYT_DATA_DIR),
}


def _java_home() -> str:
    """Return the Homebrew OpenJDK location needed by Android command-line tools."""
    return "/opt/homebrew/opt/openjdk/libexec/openjdk.jdk/Contents/Home"


def _environment() -> dict[str, str]:
    """Return the Android SDK environment for subprocesses."""
    environment = os.environ.copy()
    environment["JAVA_HOME"] = _java_home()
    environment["ANDROID_SDK_ROOT"] = str(SDK_ROOT)
    return environment


def _sdk_tool(relative_path: str) -> str:
    """Return an installed Android SDK executable path."""
    return str(SDK_ROOT / relative_path)


def _adb(serial: str, *args: str, **kwargs: object) -> subprocess.CompletedProcess:
    """Run one ADB command against the selected emulator."""
    return subprocess.run(
        [_sdk_tool("platform-tools/adb"), "-s", serial, *args],
        check=True,
        env=_environment(),
        **kwargs,
    )


def _device_serial() -> str:
    """Return the only running Android emulator serial number."""
    result = subprocess.run(
        [_sdk_tool("platform-tools/adb"), "devices"],
        check=True,
        capture_output=True,
        text=True,
        env=_environment(),
    )
    devices = [line.split()[0] for line in result.stdout.splitlines()[1:] if "\tdevice" in line]
    if len(devices) != 1:
        raise RuntimeError("Start exactly one Android emulator with: python -m skills.mobile_receipts start")
    return devices[0]


def setup() -> None:
    """Install emulator dependencies and create the persistent Google Play AVD."""
    sdkmanager = "sdkmanager"
    subprocess.run(
        [sdkmanager, f"--sdk_root={SDK_ROOT}", "--licenses"],
        check=True,
        input="y\n" * 20,
        text=True,
        env=_environment(),
    )
    subprocess.run(
        [
            sdkmanager,
            f"--sdk_root={SDK_ROOT}",
            "platform-tools",
            "emulator",
            SYSTEM_IMAGE,
        ],
        check=True,
        env=_environment(),
    )
    subprocess.run(
        [
            "avdmanager",
            "create",
            "avd",
            "--force",
            "--name",
            AVD_NAME,
            "--package",
            SYSTEM_IMAGE,
            "--device",
            "pixel_8",
        ],
        check=True,
        input="no\n",
        text=True,
        env=_environment(),
    )
    print(f"Created {AVD_NAME}. Start it with: python -m skills.mobile_receipts start")


def start() -> None:
    """Launch the persistent Google Play emulator and wait until Android has booted."""
    subprocess.Popen(
        [
            _sdk_tool("emulator/emulator"),
            "-avd",
            AVD_NAME,
            "-no-boot-anim",
        ],
        env=_environment(),
    )
    while True:
        result = subprocess.run(
            [_sdk_tool("platform-tools/adb"), "shell", "getprop", "sys.boot_completed"],
            capture_output=True,
            text=True,
            env=_environment(),
        )
        if result.stdout.strip() == "1":
            print("Android is ready.")
            return
        time.sleep(2)


def install(retailer: str) -> None:
    """Open one official Google Play listing for manual installation."""
    serial = _device_serial()
    package_name, _ = RETAILERS[retailer]
    _adb(
        serial,
        "shell",
        "am",
        "start",
        "-a",
        "android.intent.action.VIEW",
        "-d",
        f"market://details?id={package_name}",
    )
    print(f"Install {retailer} in the emulator's Play Store.")


def login(retailer: str) -> None:
    """Launch one installed retailer app for the user to authenticate interactively."""
    serial = _device_serial()
    package_name, _ = RETAILERS[retailer]
    _adb(serial, "shell", "monkey", "-p", package_name, "1")
    print(f"Sign in to {retailer} in the emulator. Credentials remain in the emulator only.")


def capture(retailer: str, receipt_date: date, pages: int) -> None:
    """Save a fixed number of receipt screens while swiping through the open ticket.

    The user opens the desired ticket first. Each screen becomes a PNG under
    the retailer's data directory, ready for ``python -m skills.ocr``.
    """
    serial = _device_serial()
    _, output_dir = RETAILERS[retailer]
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = receipt_date.strftime("%Y_%m_%d")
    for page_number in range(1, pages + 1):
        output_path = output_dir / f"{stem}_{page_number:02d}.png"
        with output_path.open("wb") as handle:
            _adb(serial, "exec-out", "screencap", "-p", stdout=handle)
        print(f"Saved {output_path.relative_to(Path.cwd())}")
        if page_number < pages:
            _adb(serial, "shell", "input", "swipe", "540", "1800", "540", "500", "300")
            time.sleep(1)


def main() -> None:
    """Parse and run the Android receipt workflow command."""
    parser = argparse.ArgumentParser(description="Carrefour and Colruyt Android receipt capture")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("setup", help="install Android SDK packages and create the emulator")
    commands.add_parser("start", help="start the persistent emulator")
    install_parser = commands.add_parser("install", help="open an official Play Store listing")
    install_parser.add_argument("retailer", choices=RETAILERS)
    login_parser = commands.add_parser("login", help="open an app for interactive sign-in")
    login_parser.add_argument("retailer", choices=RETAILERS)
    capture_parser = commands.add_parser("capture", help="save the receipt currently open in the app")
    capture_parser.add_argument("retailer", choices=RETAILERS)
    capture_parser.add_argument("receipt_date", type=date.fromisoformat)
    capture_parser.add_argument("--pages", type=int, required=True, help="number of visible receipt screens")
    args = parser.parse_args()

    if args.command == "setup":
        setup()
    elif args.command == "start":
        start()
    elif args.command == "install":
        install(args.retailer)
    elif args.command == "login":
        login(args.retailer)
    else:
        capture(args.retailer, args.receipt_date, args.pages)


if __name__ == "__main__":
    main()
