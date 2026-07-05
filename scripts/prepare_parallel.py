#!/usr/bin/env python3
"""Prepare main + worker Chrome profiles before parallel batch."""

from __future__ import annotations

import sys
from pathlib import Path

import batch_common as common


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--sync-only"]
    sync_only = "--sync-only" in sys.argv
    worker = Path(args[0]) if args else Path("chrome_profile_worker2")
    if not sync_only:
        common.ensure_login_session()
    common.sync_profile_from_main(worker)
    print(f"Ready: main + {worker.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())