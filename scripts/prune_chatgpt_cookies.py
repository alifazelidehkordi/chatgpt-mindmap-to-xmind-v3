#!/usr/bin/env python3
"""Remove automation footprint cookies while keeping ChatGPT login."""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE = ROOT / "chrome_profile" / "Default"

# Session/auth cookies that must survive pruning.
KEEP_EXACT = {
    "__Secure-next-auth.session-token.0",
    "__Secure-next-auth.session-token.1",
    "__Secure-oai-is",
    "__Host-next-auth.csrf-token",
    "__Secure-next-auth.callback-url",
    "__Host-GAPS",
    "__Host-1PLSID",
    "__Host-3PLSID",
    "ACCOUNT_CHOOSER",
    "LSID",
    "cf_clearance",
    "oai-did",
    "oai-sc",
    "_puid",
    "_uasid",
    "_umsid",
    "_account_is_fedramp",
    "oai-client-auth-info",
    "oai-client-auth-session",
    "hydra_redirect",
    "iss_context",
    "rg_context",
    "oai-allow-ne",
    "oai-chat-web-route",
    "oai-hlib",
    "oai-last-model-config",
    "oai_consent_analytics",
    "oai_consent_marketing",
    "g_state",
}

KEEP_PREFIXES = (
    "__Secure-next-auth.session-token",
    "__Secure-1P",
    "__Secure-3P",
    "APISID",
    "HSID",
    "SAPISID",
    "SID",
    "SSID",
)

DELETE_PREFIXES = (
    "conv_key_",
)

DELETE_EXACT = {
    "_dd_s",
}


def should_keep(name: str) -> bool:
    if name in DELETE_EXACT:
        return False
    if any(name.startswith(prefix) for prefix in DELETE_PREFIXES):
        return False
    if name in KEEP_EXACT:
        return True
    if any(name.startswith(prefix) for prefix in KEEP_PREFIXES):
        return True
    if name in {"__cf_bm", "_cfuvid", "__cflb", "OTZ"}:
        return True
    return False


def prune_cookies(profile_dir: Path, *, dry_run: bool = False) -> dict[str, int]:
    cookies_db = profile_dir / "Cookies"
    if not cookies_db.exists():
        raise FileNotFoundError(f"Cookies database not found: {cookies_db}")

    backup = profile_dir / f"Cookies.bak.{int(time.time())}"
    if not dry_run:
        shutil.copy2(cookies_db, backup)

    conn = sqlite3.connect(cookies_db)
    try:
        cur = conn.cursor()
        cur.execute("SELECT host_key, name, length(encrypted_value) FROM cookies")
        rows = cur.fetchall()

        to_delete: list[tuple[str, str, int]] = []
        kept = 0
        for host, name, size in rows:
            if should_keep(name):
                kept += 1
            else:
                to_delete.append((host, name, size))

        deleted_bytes = sum(size for _, _, size in to_delete)
        if not dry_run and to_delete:
            for host, name, _ in to_delete:
                cur.execute(
                    "DELETE FROM cookies WHERE host_key = ? AND name = ?",
                    (host, name),
                )
            conn.commit()

        return {
            "total": len(rows),
            "kept": kept,
            "deleted": len(to_delete),
            "deleted_bytes": deleted_bytes,
            "backup": str(backup) if not dry_run else "",
        }
    finally:
        conn.close()


def clear_cache_dirs(profile_dir: Path, *, dry_run: bool = False) -> list[str]:
    cleared: list[str] = []
    targets = [
        profile_dir / "Cache",
        profile_dir / "Code Cache",
        profile_dir / "GPUCache",
        profile_dir / "Service Worker",
    ]
    for path in targets:
        if path.exists():
            cleared.append(path.name)
            if not dry_run:
                shutil.rmtree(path, ignore_errors=True)
    return cleared


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prune ChatGPT automation cookies without removing login."
    )
    parser.add_argument(
        "--profile-dir",
        type=Path,
        default=DEFAULT_PROFILE,
        help="Chrome Default profile directory containing Cookies",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without changing files",
    )
    parser.add_argument(
        "--no-cache-clear",
        action="store_true",
        help="Only prune cookies; do not clear browser cache folders",
    )
    args = parser.parse_args()

    stats = prune_cookies(args.profile_dir, dry_run=args.dry_run)
    cache = [] if args.no_cache_clear else clear_cache_dirs(args.profile_dir, dry_run=args.dry_run)

    mode = "DRY RUN" if args.dry_run else "DONE"
    print(f"[{mode}] Cookie prune for {args.profile_dir}")
    print(f"  total cookies : {stats['total']}")
    print(f"  kept (login)  : {stats['kept']}")
    print(f"  deleted       : {stats['deleted']} ({stats['deleted_bytes']} bytes)")
    if stats["backup"]:
        print(f"  backup        : {stats['backup']}")
    if cache:
        print(f"  cache cleared : {', '.join(cache)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())