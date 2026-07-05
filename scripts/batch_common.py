from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import run_chatgpt_temporary_test as core
from opml_utils import repair_and_validate_opml
from selenium_browser import copy_login_session, has_auth_cookies, real_chrome_available, run_login_for_profile

ROOT = core.ROOT
LOGS_DIR = ROOT / "logs"
MAIN_CHROME_PROFILE = ROOT / "chrome_profile"
SKIP_NAME_PREFIXES = ("00_INDEX", "00_SPLIT_INDEX", "INDEX")
SKIP_NAME_STEMS = {"README", "INDEX"}


def batch_log(message: str) -> None:
    core.log(message)


def should_skip_input(path: Path) -> bool:
    stem_upper = path.stem.upper()
    if stem_upper in SKIP_NAME_STEMS:
        return True
    return any(stem_upper.startswith(prefix) for prefix in SKIP_NAME_PREFIXES)


def collect_input_files(input_dir: Path) -> list[Path]:
    patterns = ("*.pdf", "*.docx", "*.md", "*.tex")
    files: list[Path] = []
    for pattern in patterns:
        files.extend(path.resolve() for path in input_dir.glob(pattern) if path.is_file())
    unique = sorted({path for path in files if not should_skip_input(path)}, key=lambda p: p.name.lower())
    return unique


def wait_for_download(before: set[Path], timeout: int = 90) -> Path | None:
    if hasattr(core, "resolve_download"):
        return core.resolve_download(None, before, timeout=timeout, click=False)
    if hasattr(core, "wait_and_salvage_download"):
        return core.wait_and_salvage_download(before, timeout=timeout)
    deadline = time.time() + timeout
    while time.time() < deadline:
        downloaded = core.newest_download(before)
        if downloaded:
            return downloaded
        time.sleep(1)
    return None


def is_browser_crash_error(exc: Exception) -> bool:
    message = str(exc).lower()
    markers = (
        "epipe",
        "target closed",
        "browser has been closed",
        "browser window was closed",
        "connection closed",
        "session closed",
        "protocol error",
    )
    return any(marker in message for marker in markers)


def driver_is_alive(driver) -> bool:
    if driver is None:
        return False
    try:
        _ = driver.title
        return True
    except Exception as exc:
        if is_browser_crash_error(exc):
            return False
        return False


def quit_driver(driver) -> None:
    if driver is None:
        return
    try:
        driver.quit()
    except Exception:
        pass


def reset_chat(driver, model: str | None) -> None:
    core.start_new_chat(driver)
    if model:
        core.select_model(driver, model)


def is_temporary_chat_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "temporary chat" in message or "prompt editor" in message


def recover_from_chat_error(
    driver,
    model: str | None,
    *,
    skip_warmup: bool = False,
):
    batch_log("Recovering from temporary-chat load failure...")
    if driver_is_alive(driver):
        removed = prune_driver_cookies(driver)
        if removed:
            try:
                reset_chat(driver, model)
                return driver
            except Exception as exc:
                batch_log(f"Live cookie prune retry failed: {exc}")
        quit_driver(driver)
    prune_automation_cookies()
    return recreate_driver(model, skip_warmup=skip_warmup)


def recreate_driver(model: str | None, *, skip_warmup: bool = False):
    batch_log("Detected dead or disconnected browser session. Recreating driver...")
    quit_driver(None)
    if os.environ.get("CHATGPT_SYNC_PROFILE_FROM", "").strip():
        sync_profile_from_main()
    clear_profile_locks(core.CHROME_PROFILE_DIR)
    prune_automation_cookies()
    driver = core.build_driver(browser="chrome")
    driver.set_window_size(1400, 950)
    driver.get(core.CHATGPT_URL)
    batch_log("Checking login state...")
    if _playwright_needs_login(driver, probe_seconds=8):
        quit_driver(driver)
        _recover_playwright_login()
        clear_profile_locks(core.CHROME_PROFILE_DIR)
        driver = core.build_driver(browser="chrome")
        driver.set_window_size(1400, 950)
        driver.get(core.CHATGPT_URL)
    core.wait_until_logged_in(driver, timeout=120)
    batch_log("Logged-in chat box is visible.")
    if not skip_warmup:
        warm_up(driver, model)
    else:
        reset_chat(driver, model)
    return driver


def warm_up(driver, model: str | None) -> None:
    batch_log("Warm-up: opening temporary chat and sending hello.")
    reset_chat(driver, model)
    expected_assistant_count = core.assistant_message_count(driver) + 1
    core.send_message(driver, "hello")
    core.wait_until_idle(driver, min_assistant_count=expected_assistant_count)
    batch_log("Warm-up complete.")


DELETE_COOKIE_PREFIXES = ("conv_key_",)
DELETE_COOKIE_EXACT = {"_dd_s"}


def should_delete_cookie(name: str) -> bool:
    if name in DELETE_COOKIE_EXACT:
        return True
    return any(name.startswith(prefix) for prefix in DELETE_COOKIE_PREFIXES)


def prune_driver_cookies(driver) -> int:
    """Remove temporary-chat cookies via the browser session while it stays open."""
    if not driver_is_alive(driver):
        return 0
    removed = 0
    for cookie in driver.get_cookies():
        name = cookie.get("name", "")
        if not should_delete_cookie(name):
            continue
        try:
            driver.delete_cookie(name)
            removed += 1
        except Exception:
            pass
    if removed:
        batch_log(f"Pruned {removed} automation cookie(s) from live session.")
    return removed


def clear_profile_locks(profile_dir: Path) -> None:
    for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        path = profile_dir / name
        if path.exists():
            path.unlink(missing_ok=True)
        default_path = profile_dir / "Default" / name
        if default_path.exists():
            default_path.unlink(missing_ok=True)


def sync_profile_from_main(target_profile: Path | None = None) -> None:
    """Copy auth session from main chrome_profile into a worker profile."""
    source = Path(os.environ.get("CHATGPT_SYNC_PROFILE_FROM", MAIN_CHROME_PROFILE))
    target = target_profile or core.CHROME_PROFILE_DIR
    if source.resolve() == target.resolve():
        return
    if not has_auth_cookies(source):
        raise RuntimeError(f"No login session in main profile: {source}")
    clear_profile_locks(target)
    copy_login_session(source, target)
    batch_log(f"Synced login session: {source.name} -> {target.name}")


def prune_automation_cookies() -> None:
    if os.environ.get("CHATGPT_SKIP_COOKIE_PRUNE") == "1":
        batch_log("Skipping cookie prune (worker profile sync).")
        return
    profile_default = core.CHROME_PROFILE_DIR / "Default"
    cookies_db = profile_default / "Cookies"
    if not cookies_db.exists():
        batch_log("Skipping cookie prune — no Cookies database yet.")
        return

    script = ROOT / "scripts" / "prune_chatgpt_cookies.py"
    if not script.exists():
        return
    import subprocess
    import sys

    batch_log("Pruning automation cookies (keeping login session)...")
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--profile-dir",
            str(profile_default),
            "--no-cache-clear",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    for line in (result.stdout or "").strip().splitlines():
        batch_log(line)
    if result.returncode != 0:
        batch_log(f"Cookie prune warning: {result.stderr.strip() or result.returncode}")


def ensure_login_session() -> None:
    """macwili-style: use real Chromium for first login, then reuse saved profile."""
    if os.environ.get("CHATGPT_SKIP_REAL_CHROME_LOGIN") == "1":
        return

    profile_dir = core.CHROME_PROFILE_DIR
    if has_auth_cookies(profile_dir) and os.environ.get("CHATGPT_FORCE_REAL_CHROME_LOGIN") != "1":
        batch_log(f"Login session found in {profile_dir.name}/ (will verify in browser)")
        return

    if not real_chrome_available():
        raise RuntimeError(
            "No ChatGPT login session and no real Chromium installed. "
            "Run: sudo dnf install chromium"
        )

    batch_log("First run: Playwright stealth cannot pass Google login.")
    run_login_for_profile(target_profile=profile_dir)


def _playwright_needs_login(driver, *, probe_seconds: int = 12) -> bool:
    deadline = time.time() + probe_seconds
    while time.time() < deadline:
        try:
            core.wait_until_logged_in(driver, timeout=4)
            return False
        except Exception as exc:
            message = str(exc).lower()
            if "google blocked sign-in" in message:
                return True
            if "timed out" in message:
                time.sleep(1)
                continue
            raise
    return True


def _recover_playwright_login() -> None:
    """Never open Selenium during parallel workers — sync cookies from main profile instead."""
    if os.environ.get("CHATGPT_SKIP_REAL_CHROME_LOGIN") == "1":
        sync_profile_from_main()
        return
    batch_log("Playwright Chromium is not logged in (Google blocks sign-in here).")
    run_login_for_profile(target_profile=core.CHROME_PROFILE_DIR)


def bootstrap_session(model: str | None, *, skip_warmup: bool = False):
    sync_from = os.environ.get("CHATGPT_SYNC_PROFILE_FROM", "").strip()
    if sync_from:
        sync_profile_from_main()
    else:
        ensure_login_session()
    clear_profile_locks(core.CHROME_PROFILE_DIR)
    prune_automation_cookies()
    driver = core.build_driver(browser="chrome")
    driver.set_window_size(1400, 950)
    driver.get(core.CHATGPT_URL)
    batch_log("ChatGPT opened.")
    batch_log("Checking login state...")
    if _playwright_needs_login(driver):
        quit_driver(driver)
        _recover_playwright_login()
        clear_profile_locks(core.CHROME_PROFILE_DIR)
        prune_automation_cookies()
        driver = core.build_driver(browser="chrome")
        driver.set_window_size(1400, 950)
        driver.get(core.CHATGPT_URL)
        batch_log("Retrying automation browser with saved session...")
        core.wait_until_logged_in(driver, timeout=120)
    else:
        batch_log("Logged-in chat box is visible.")
    if skip_warmup:
        reset_chat(driver, model)
        batch_log("Skipped warm-up hello message.")
    else:
        warm_up(driver, model)
    return driver


def save_artifact_download(
    downloaded: Path,
    output_path: Path,
    *,
    validate: bool = True,
) -> None:
    if output_path.exists():
        output_path.unlink()
    downloaded.replace(output_path)
    if validate and output_path.suffix.lower() == ".opml":
        repair_and_validate_opml(output_path)


def save_opml_download(
    downloaded: Path,
    output_path: Path,
    *,
    validate: bool = True,
) -> None:
    save_artifact_download(downloaded, output_path, validate=validate)


def write_batch_summary(
    *,
    mode: str,
    successes: int,
    failures: list[str],
    output_dir: Path,
    extra: dict | None = None,
) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "successes": successes,
        "failure_count": len(failures),
        "failures": failures,
        "output_dir": str(output_dir),
    }
    if extra:
        payload.update(extra)
    summary_path = LOGS_DIR / "last_batch_summary.json"
    summary_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    batch_log(f"Batch summary saved: {summary_path}")


def run_with_retries(
    label: str,
    driver,
    model: str | None,
    process_once: Callable[[object], bool],
    *,
    max_attempts: int = 3,
    retry_delay: int = 5,
    skip_warmup: bool = False,
) -> tuple[bool, object]:
    for attempt in range(1, max_attempts + 1):
        try:
            if not driver_is_alive(driver):
                quit_driver(driver)
                driver = recreate_driver(model, skip_warmup=skip_warmup)

            if attempt > 1:
                batch_log(f"Retrying {label} (attempt {attempt}/{max_attempts})...")

            if process_once(driver):
                return True, driver

            batch_log("No OPML obtained. Opening a fresh chat for next attempt.")
            if driver_is_alive(driver):
                reset_chat(driver, model)
            else:
                quit_driver(driver)
                driver = recreate_driver(model, skip_warmup=skip_warmup)
        except Exception as exc:
            batch_log(f"ERROR on attempt {attempt}/{max_attempts} for {label}: {exc}")
            if is_browser_crash_error(exc) or not driver_is_alive(driver):
                batch_log("Browser crashed or disconnected — recreating session...")
                quit_driver(driver)
                driver = recreate_driver(model, skip_warmup=skip_warmup)
            elif is_temporary_chat_error(exc):
                driver = recover_from_chat_error(driver, model, skip_warmup=skip_warmup)
            elif driver_is_alive(driver):
                reset_chat(driver, model)
            else:
                quit_driver(driver)
                driver = recreate_driver(model, skip_warmup=skip_warmup)
        if attempt < max_attempts:
            time.sleep(retry_delay)
    return False, driver