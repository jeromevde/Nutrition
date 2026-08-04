#!/usr/bin/env python3
"""
skills.serve — build the report and run it locally.

    python3 -m skills.serve            # build, serve, open the browser
    python3 -m skills.serve --port 9000
    python3 -m skills.serve --no-open
    python3 -m skills.serve --no-build # serve what is already in public/

Serving over http://127.0.0.1 rather than file:// is what makes the service
worker register and the install-as-app prompt appear; from file:// the page
still works, it just is not installable.
"""

from __future__ import annotations

import argparse
import http.server
import socket
import socketserver
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "public"


def free_port(preferred: int) -> int:
    for port in [preferred] + list(range(preferred + 1, preferred + 20)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit(f"No free port near {preferred}")


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(PUBLIC), **kw)

    def end_headers(self):
        # A stale document under a fresh trust badge is the one failure this
        # app must not have, so nothing is cached by the dev server either.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        if "GET /index.html" in (fmt % args) or "GET / " in (fmt % args):
            sys.stderr.write(f"  · {fmt % args}\n")


def build() -> None:
    for mod in ("skills.rebuild", "skills.report_html"):
        r = subprocess.run([sys.executable, "-m", mod], cwd=ROOT,
                           capture_output=True, text=True)
        if r.returncode:
            sys.stderr.write(r.stdout + r.stderr)
            raise SystemExit(f"{mod} failed")
        print(r.stdout.rstrip())


def main() -> None:
    ap = argparse.ArgumentParser(description="Build and serve the Paniere PWA")
    ap.add_argument("--port", type=int, default=8791)
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--no-build", action="store_true")
    args = ap.parse_args()

    if not args.no_build:
        build()
    if not (PUBLIC / "index.html").exists():
        raise SystemExit("public/index.html missing — run without --no-build")

    port = free_port(args.port)
    url = f"http://127.0.0.1:{port}/index.html"

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", port), Handler) as httpd:
        print(f"\n  Paniere  →  {url}")
        if port != args.port:
            print(f"  (port {args.port} was busy)")
        print("  Ctrl-C to stop\n")
        if not args.no_open:
            threading.Timer(0.4, lambda: webbrowser.open(url)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n  stopped")


if __name__ == "__main__":
    main()
