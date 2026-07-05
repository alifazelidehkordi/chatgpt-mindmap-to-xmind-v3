"""Real Chrome/Edge via Selenium — used for first-time Google/ChatGPT login."""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

ROOT = Path(__file__).resolve().parent.parent
CHROME_PROFILE_DIR = Path(os.environ.get("CHATGPT_CHROME_PROFILE_DIR", ROOT / "chrome_profile"))
LOGIN_PROFILE_DIR = Path(
    os.environ.get("CHATGPT_LOGIN_PROFILE_DIR", ROOT / "chrome_profile_login")
)
EDGE_PROFILE_DIR = Path(os.environ.get("CHATGPT_EDGE_PROFILE_DIR", ROOT / "edge_profile"))
DOWNLOAD_DIR = Path(os.environ.get("CHATGPT_DOWNLOAD_DIR", ROOT / "downloads"))
CHATGPT_URL = "https://chatgpt.com/?temporary-chat=true"

LOCAL_GOOGLE_CHROME = Path.home() / ".local" / "chrome-install" / "opt" / "google" / "chrome" / "google-chrome"
CHROME_CANDIDATES = [
    Path("/usr/bin/chromium-browser"),
    Path("/usr/bin/chromium"),
    Path("/usr/bin/google-chrome-stable"),
    Path("/usr/bin/google-chrome"),
    Path("/opt/google/chrome/google-chrome"),
    LOCAL_GOOGLE_CHROME,
    Path("/snap/bin/chromium"),
    Path.home() / ".local" / "share" / "flatpak" / "exports" / "bin" / "com.google.Chrome",
]
EDGE_CANDIDATES = [
    Path("/usr/bin/microsoft-edge"),
    Path("/usr/bin/microsoft-edge-stable"),
]
CHROME_NAMES = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"]
EDGE_NAMES = ["microsoft-edge", "microsoft-edge-stable"]


AUTH_COOKIE_MARKERS = {
    "__Secure-next-auth.session-token.0",
    "__Secure-oai-is",
    "oai-did",
    "cf_clearance",
}


def log(message: str) -> None:
    print(message, flush=True)


def has_auth_cookies(profile_dir: Path) -> bool:
    cookies_db = profile_dir / "Default" / "Cookies"
    if not cookies_db.exists() or cookies_db.stat().st_size < 512:
        return False
    try:
        import sqlite3

        conn = sqlite3.connect(f"file:{cookies_db}?mode=ro", uri=True)
        try:
            names = {row[0] for row in conn.execute("SELECT name FROM cookies")}
        finally:
            conn.close()
    except Exception:
        return False
    if names & AUTH_COOKIE_MARKERS:
        return True
    return any(name.startswith("__Secure-next-auth.session-token") for name in names)


def real_chrome_available() -> bool:
    return find_browser_binary(CHROME_CANDIDATES, CHROME_NAMES) is not None


def find_browser_binary(candidates: list[Path], names: list[str]) -> Path | None:
    override = os.environ.get("CHATGPT_CHROME_BINARY", "").strip()
    if override:
        path = Path(override)
        if path.exists():
            return path
        found = shutil.which(override)
        if found:
            return Path(found)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    for name in names:
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def copy_login_session(
    login_profile: Path = LOGIN_PROFILE_DIR,
    target_profile: Path = CHROME_PROFILE_DIR,
) -> None:
    """Copy auth cookies from real-Chrome login profile into Playwright profile."""
    src = login_profile / "Default"
    dst = target_profile / "Default"
    if not (src / "Cookies").exists():
        raise FileNotFoundError(f"No Cookies database in login profile: {src}")
    dst.mkdir(parents=True, exist_ok=True)
    names = (
        "Cookies",
        "Cookies-journal",
        "Login Data",
        "Login Data-journal",
        "Web Data",
        "Web Data-journal",
        "Local Storage",
        "Session Storage",
        "IndexedDB",
    )
    copied = 0
    for name in names:
        src_path = src / name
        if not src_path.exists():
            continue
        dst_path = dst / name
        if src_path.is_dir():
            if dst_path.exists():
                shutil.rmtree(dst_path)
            shutil.copytree(src_path, dst_path)
        else:
            shutil.copy2(src_path, dst_path)
        copied += 1
    log(f"Copied {copied} session item(s) from {login_profile.name} -> {target_profile.name}")


def build_driver(
    *,
    headless: bool = False,
    browser: str = "chrome",
    profile_dir: Path | None = None,
):
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    if browser == "edge":
        profile_dir = profile_dir or EDGE_PROFILE_DIR
        options = EdgeOptions()
        binary = find_browser_binary(EDGE_CANDIDATES, EDGE_NAMES)
        if binary is None:
            raise RuntimeError(
                "Microsoft Edge was not found. Install Edge or set CHATGPT_CHROME_BINARY."
            )
        options.binary_location = str(binary)
        service = EdgeService()
        driver_factory = webdriver.Edge
    else:
        profile_dir = profile_dir or CHROME_PROFILE_DIR
        options = ChromeOptions()
        binary = find_browser_binary(CHROME_CANDIDATES, CHROME_NAMES)
        if binary is None:
            raise RuntimeError(
                "Chrome/Chromium was not found. Install google-chrome or chromium, "
                "or set CHATGPT_CHROME_BINARY to the browser executable."
            )
        options.binary_location = str(binary)
        service = ChromeService()
        driver_factory = webdriver.Chrome

    profile_dir.mkdir(parents=True, exist_ok=True)
    options.add_argument(f"--user-data-dir={profile_dir}")
    options.add_argument("--profile-directory=Default")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    # Do NOT pass --no-sandbox / --disable-gpu here — Google rejects sign-in.
    options.add_experimental_option(
        "excludeSwitches", ["enable-automation", "enable-logging"]
    )
    options.add_experimental_option("useAutomationExtension", False)
    options.add_experimental_option(
        "prefs",
        {
            "download.default_directory": str(DOWNLOAD_DIR.resolve()),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
        },
    )
    if headless:
        options.add_argument("--headless=new")

    log(f"Launching real browser (Selenium): {binary.name} — profile: {profile_dir}")
    driver = driver_factory(service=service, options=options)
    driver.set_window_size(1400, 950)
    return driver


def wait_for_editor(driver, timeout: int = 120):
    selectors = [
        (By.CSS_SELECTOR, "#prompt-textarea"),
        (By.CSS_SELECTOR, "div[contenteditable='true'][data-placeholder]"),
        (By.CSS_SELECTOR, "div[contenteditable='true']"),
        (By.CSS_SELECTOR, "textarea"),
    ]
    end = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < end:
        for by, selector in selectors:
            try:
                element = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((by, selector))
                )
                if element.is_displayed() and element.is_enabled():
                    return element
            except Exception as exc:
                last_error = exc
        time.sleep(1)
    raise TimeoutError(f"Could not find ChatGPT prompt editor: {last_error}")


def dismiss_cookie_banner(driver) -> None:
    for label in ("Accept all", "Reject non-essential"):
        buttons = driver.find_elements(
            By.XPATH, f"//button[contains(normalize-space(.), '{label}')]"
        )
        for button in buttons:
            try:
                if button.is_displayed() and button.is_enabled():
                    button.click()
                    time.sleep(1)
                    return
            except Exception:
                continue


def login_buttons_visible(driver) -> bool:
    buttons = driver.find_elements(
        By.XPATH,
        "//button[contains(normalize-space(.), 'Log in') or contains(normalize-space(.), 'Sign up')]"
        " | //a[contains(normalize-space(.), 'Log in') or contains(normalize-space(.), 'Sign up')]",
    )
    return any(button.is_displayed() for button in buttons)


def wait_until_logged_in(driver, timeout: int = 900) -> None:
    deadline = time.time() + timeout
    warned = False
    while time.time() < deadline:
        dismiss_cookie_banner(driver)
        if not login_buttons_visible(driver):
            try:
                wait_for_editor(driver, timeout=30)
                log("Login successful — ChatGPT editor is ready.")
                return
            except TimeoutError:
                log("Editor not visible yet; waiting...")
                time.sleep(2)
                continue
        if not warned:
            log("")
            log(">>> LOGIN REQUIRED (real Chrome)")
            log(">>> In the Chrome window: click Log in, sign in with Google, then return here.")
            log(">>> Do NOT close the browser — the script will continue automatically.")
            log("")
            warned = True
        time.sleep(3)
    raise TimeoutError("Timed out waiting for ChatGPT login.")


def run_login_for_profile(
    *,
    target_profile: Path | None = None,
    browser: str = "chrome",
) -> None:
    """Log in via real Chromium, then copy session into the Playwright profile."""
    target = target_profile or CHROME_PROFILE_DIR
    if not real_chrome_available():
        raise RuntimeError(
            "Real Chromium/Chrome not found. Install with: sudo dnf install chromium"
        )

    log("")
    log(">>> Google blocks login in Playwright Chromium.")
    log(">>> Opening real Chromium for sign-in — batch will continue automatically.")
    log(f">>> Profile will be saved to: {target}")
    log("")

    driver = build_driver(headless=False, browser=browser, profile_dir=LOGIN_PROFILE_DIR)
    try:
        driver.get(CHATGPT_URL)
        wait_until_logged_in(driver)
        copy_login_session(LOGIN_PROFILE_DIR, target)
        log("Login session saved. Continuing with automation browser...")
        time.sleep(2)
    finally:
        driver.quit()


def run_login(browser: str = "chrome") -> int:
    try:
        run_login_for_profile(target_profile=CHROME_PROFILE_DIR, browser=browser)
        log("Done. You can now run ./run_pdf_to_xmind.sh")
        return 0
    except Exception as exc:
        log(f"ERROR: {exc}")
        return 1