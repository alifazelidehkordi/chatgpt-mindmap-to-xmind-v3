#!/usr/bin/env python3
"""Open real Chrome for first-time ChatGPT/Google login (avoids Google bot detection)."""

from __future__ import annotations

import argparse
import sys

from selenium_browser import run_login


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Log in to ChatGPT using real Chrome (not Playwright Chromium)."
    )
    parser.add_argument(
        "--browser",
        choices=("chrome", "edge"),
        default="chrome",
        help="Browser to use (default: chrome)",
    )
    args = parser.parse_args()
    try:
        return run_login(browser=args.browser)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())