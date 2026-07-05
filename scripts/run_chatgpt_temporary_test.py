from __future__ import annotations

import argparse
import asyncio
import os
import re
import shutil
import sys
import threading
import time
from pathlib import Path

from patchright.async_api import BrowserContext, Page, Playwright, async_playwright
from playwright_stealth import Stealth

STEALTH_AVAILABLE = True

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROMPT = ROOT / "prompts" / "prompt-mind-map.md"
CHROME_PROFILE_DIR = Path(os.environ.get("CHATGPT_CHROME_PROFILE_DIR", ROOT / "chrome_profile"))
DOWNLOAD_DIR = Path(os.environ.get("CHATGPT_DOWNLOAD_DIR", ROOT / "downloads"))
TEXT_OUTPUT = ROOT / "last_response.txt"
SCREENSHOT = ROOT / "last_state.png"
LOG_FILE = Path(os.environ.get("CHATGPT_RUN_LOG", ROOT / "run.log"))
CHATGPT_URL = "https://chatgpt.com/?temporary-chat=true"

EDITOR_SELECTORS = [
    "#prompt-textarea",
    "div[contenteditable='true'][data-placeholder]",
    "div[contenteditable='true']",
    "textarea",
]

STOP_BUTTON_SELECTOR = (
    "button[data-testid='stop-button'], button[aria-label*='Stop'], button[aria-label*='stop']"
)
LONG_GENERATION_STOP_SECONDS = int(os.environ.get("LONG_GENERATION_STOP_SECONDS", "900"))
POST_STOP_GRACE_SECONDS = int(os.environ.get("POST_STOP_GRACE_SECONDS", "60"))
RATE_LIMIT_WAIT_SECONDS = int(os.environ.get("RATE_LIMIT_WAIT_SECONDS", "180"))

ATTACH_BUTTON_SELECTORS = [
    "button[data-testid='composer-plus-btn']",
    "button[aria-label*='Attach']",
    "button[aria-label*='Upload']",
]

PARTIAL_SUFFIXES = (".crdownload", ".tmp", ".part", ".download")
NON_FILE_DOWNLOAD_PHRASES = (
    "download apps",
    "get chatgpt mobile",
    "chatgpt mobile",
    "app store",
    "google play",
)
ARTIFACT_EXTENSIONS = (".opml", ".md", ".markdown", ".tex")

_LOOP = asyncio.new_event_loop()
_LOOP_LOCK = threading.Lock()


def _run(coro):
    with _LOOP_LOCK:
        return _LOOP.run_until_complete(coro)


def log(message: str) -> None:
    print(message, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(message + "\n")


async def _dismiss_rate_limit_modal(page: Page) -> bool:
    try:
        modal = page.locator("#modal-conversation-history-rate-limit").first
        body_text = await page.locator("body").inner_text(timeout=1000)
        if not await modal.is_visible(timeout=500) and "Too many requests" not in body_text:
            return False
        button = page.locator("button:has-text('Got it')").first
        if await button.is_visible():
            await button.click()
        log(f"Rate limit modal dismissed; waiting {RATE_LIMIT_WAIT_SECONDS}s.")
        await asyncio.sleep(RATE_LIMIT_WAIT_SECONDS)
        return True
    except Exception:
        return False


def normalize_persian_text(text: str) -> str:
    return (
        text.replace("\u200c", "")
        .replace("\u200d", "")
        .replace("\u00a0", " ")
        .strip()
    )


def is_partial_download(path: Path) -> bool:
    name = path.name.lower()
    return any(name.endswith(suffix) for suffix in PARTIAL_SUFFIXES)


def is_artifact_download_file(path: Path) -> bool:
    name = path.name.lower()
    suffix = path.suffix.lower()
    if any(ext in name or suffix == ext for ext in ARTIFACT_EXTENSIONS):
        return True
    try:
        if path.stat().st_size > 5_000_000:
            return False
        sample = path.read_text(encoding="utf-8", errors="ignore")[:4096].lower()
    except OSError:
        return False
    if "<opml" in sample:
        return True
    stripped = sample.strip()
    if stripped.startswith("#") or "\n## " in sample or "\n### " in sample:
        return True
    if "\\section{" in sample or "\\chapter{" in sample or "\\begin{document}" in sample:
        return True
    return False


is_opml_download_file = is_artifact_download_file


def score_persian_download_text(text: str) -> int:
    normalized = normalize_persian_text(text).lower()
    if "دانلود فایل ترجمه" in normalized:
        return 100
    if "دانلود فایل" in normalized:
        return 80
    if "دانلود" in normalized:
        return 50
    return 0


def is_artifact_download_trigger(
    *,
    text: str = "",
    href: str = "",
    title: str = "",
    aria: str = "",
) -> bool:
    direct = " ".join(field for field in (text, title, aria) if field)
    haystack = f"{direct} {href}".lower()
    if any(phrase in haystack for phrase in NON_FILE_DOWNLOAD_PHRASES):
        return False

    href_lower = href.lower()
    if score_persian_download_text(direct) > 0:
        return True
    if href_lower.startswith("sandbox:") or "sandbox:" in href_lower:
        return True
    if any(ext in href_lower for ext in ARTIFACT_EXTENSIONS):
        return True
    if "/download" in href_lower or "/file-" in href_lower:
        return True

    direct_lower = direct.lower()
    if "download" in direct_lower and any(
        token in direct_lower
        for token in (".opml", ".md", ".tex", "markdown", "opml", "mind map", "notes")
    ):
        return True
    return False


is_opml_download_trigger = is_artifact_download_trigger


def newest_download(before: set[Path]) -> Path | None:
    current = set(DOWNLOAD_DIR.glob("*"))
    candidates = [
        path
        for path in current - before
        if path.is_file() and not is_partial_download(path) and is_artifact_download_file(path)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def pending_downloads(before: set[Path]) -> list[Path]:
    current = set(DOWNLOAD_DIR.glob("*"))
    return sorted(
        [path for path in current - before if path.is_file() and is_partial_download(path)],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def find_artifact_candidates_in_downloads(before: set[Path]) -> list[Path]:
    current = set(DOWNLOAD_DIR.glob("*"))
    new_files = [
        p
        for p in (current - before)
        if p.is_file() and not p.name.endswith((".crdownload", ".tmp", ".part"))
    ]
    artifact_like = [p for p in new_files if is_artifact_download_file(p)]
    return sorted(artifact_like, key=lambda p: p.stat().st_mtime, reverse=True)


find_opml_candidates_in_downloads = find_artifact_candidates_in_downloads


def wait_for_download_settled(before: set[Path], timeout: int = 90) -> Path | None:
    deadline = time.time() + timeout
    last_logged = 0.0

    while time.time() < deadline:
        partial = pending_downloads(before)
        if partial:
            if time.time() - last_logged > 10:
                log(f"Download in progress: {[p.name for p in partial]}")
                last_logged = time.time()
            time.sleep(1.0)
            continue

        downloaded = newest_download(before)
        if downloaded:
            return downloaded

        candidates = find_artifact_candidates_in_downloads(before)
        if candidates:
            return candidates[0]

        time.sleep(1.0)

    return newest_download(before) or (find_artifact_candidates_in_downloads(before) or [None])[0]


def wait_and_salvage_download(before: set[Path], timeout: int = 90) -> Path | None:
    deadline = time.time() + timeout
    last_logged = 0.0
    while time.time() < deadline:
        dl = wait_for_download_settled(before, timeout=3)
        if dl:
            return dl
        if time.time() - last_logged > 12:
            partial = pending_downloads(before)
            if partial:
                log(f"Still waiting for download to finish: {[p.name for p in partial]}")
            else:
                log("Still waiting for any new file in downloads/ ...")
            last_logged = time.time()
        time.sleep(1.2)
    candidates = find_opml_candidates_in_downloads(before)
    return candidates[0] if candidates else None


class PlaywrightDriver:
    """Thin sync wrapper so batch_common.py can keep its Selenium-shaped API."""

    def __init__(self, playwright: Playwright, context: BrowserContext, page: Page, *, headless: bool):
        self._playwright = playwright
        self._context = context
        self.page = page
        self._headless = headless
        self._closed = False

    @property
    def title(self) -> str:
        return _run(self.page.title())

    def quit(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            _run(self._context.close())
        except Exception:
            pass
        try:
            _run(self._playwright.stop())
        except Exception:
            pass

    def get(self, url: str) -> None:
        _run(self.page.goto(url))

    def set_window_size(self, width: int, height: int) -> None:
        _run(self.page.set_viewport_size({"width": width, "height": height}))

    def get_cookies(self) -> list[dict]:
        return _run(self._context.cookies())

    def delete_cookie(self, name: str) -> None:
        cookies = _run(self._context.cookies())
        keep = [cookie for cookie in cookies if cookie.get("name") != name]
        _run(self._context.clear_cookies())
        if keep:
            _run(self._context.add_cookies(keep))

    def save_screenshot(self, path: str) -> None:
        _run(self.page.screenshot(path=path, full_page=True))


def _system_chromium_path() -> str | None:
    override = os.environ.get("CHATGPT_CHROME_BINARY", "").strip()
    if override:
        return override
    for name in ("chromium-browser", "chromium", "google-chrome-stable", "google-chrome"):
        found = shutil.which(name)
        if found:
            return found
    return None


async def _launch_playwright(headless: bool, profile_dir: Path | None = None):
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    profile = profile_dir or Path(os.environ.get("CHATGPT_CHROME_PROFILE_DIR", CHROME_PROFILE_DIR))
    profile.mkdir(parents=True, exist_ok=True)

    playwright = await async_playwright().start()
    launch_kwargs: dict = {
        "user_data_dir": str(profile),
        "headless": headless,
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-dev-shm-usage",
        ],
        "downloads_path": str(DOWNLOAD_DIR),
        "viewport": {"width": 1400, "height": 950},
    }
    chromium_bin = _system_chromium_path()
    if chromium_bin and os.environ.get("CHATGPT_USE_BUNDLED_CHROMIUM") != "1":
        launch_kwargs["executable_path"] = chromium_bin
        log(f"Using system Chromium: {chromium_bin}")
    context = await playwright.chromium.launch_persistent_context(**launch_kwargs)
    page = context.pages[0] if context.pages else await context.new_page()
    if STEALTH_AVAILABLE:
        await Stealth().apply_stealth_async(page)

    log(f"Launching Patchright (stealth) — profile: {profile}")
    return playwright, context, page


def build_driver(headless: bool = False, browser: str = "chrome") -> PlaywrightDriver:
    if browser != "chrome":
        log(f"Note: Playwright migration uses Chromium only (requested {browser})")
    playwright, context, page = _run(_launch_playwright(headless))
    return PlaywrightDriver(playwright, context, page, headless=headless)


async def _wait_for_editor(page: Page, timeout: int = 120) -> None:
    end = time.time() + timeout
    last_error = None

    while time.time() < end:
        for selector in EDITOR_SELECTORS:
            try:
                locator = page.locator(selector).first
                await locator.wait_for(state="visible", timeout=5000)
                if await locator.is_enabled():
                    return
            except Exception as exc:
                last_error = exc
        await asyncio.sleep(1)

    raise TimeoutError(f"Could not find ChatGPT prompt editor: {last_error}")


async def _dismiss_cookie_banner(page: Page) -> None:
    for label in ("Accept all", "Reject non-essential"):
        try:
            btn = page.get_by_role("button", name=label).first
            if await btn.is_visible():
                await btn.click()
                await asyncio.sleep(1)
                return
        except Exception:
            continue


async def _login_buttons_visible(page: Page) -> bool:
    try:
        login = page.get_by_role("button", name=re.compile(r"Log in|Sign up", re.I)).first
        return await login.is_visible()
    except Exception:
        return False


async def _cloudflare_challenge_visible(page: Page) -> bool:
    try:
        text = (await page.locator("body").inner_text(timeout=2000)).lower()
        return (
            "verify you are human" in text
            or "checking your browser" in text
            or "just a moment" in text
        )
    except Exception:
        return False


async def _wait_until_logged_in(page: Page, timeout: int = 600, headless: bool = False) -> None:
    deadline = time.time() + timeout
    login_prompted = False
    cloudflare_prompted = False
    reload_count = 0

    while time.time() < deadline:
        await _dismiss_cookie_banner(page)
        if await _cloudflare_challenge_visible(page):
            if not cloudflare_prompted:
                log(">>> Cloudflare check: click 'Verify you are human' in the browser window.")
                log(">>> Do NOT close the window — script will continue automatically.")
                cloudflare_prompted = True
            await asyncio.sleep(3)
            continue
        if await _login_buttons_visible(page):
            if headless:
                raise RuntimeError(
                    "Login required but running in headless mode. "
                    "Use a pre-logged chrome_profile/ or run without --headless first."
                )
            if not login_prompted:
                body = ""
                try:
                    body = (await page.locator("body").inner_text(timeout=2000)).lower()
                except Exception:
                    pass
                if "browser or app may not be secure" in body or "couldn't sign you in" in body:
                    raise RuntimeError(
                        "Google blocked sign-in in Playwright Chromium. "
                        "Close this window — the script will open real Chromium for login."
                    )
                log(">>> Waiting for saved login session (do NOT sign in with Google here).")
                log(">>> If this persists, the script will switch to real Chromium automatically.")
                login_prompted = True
            await asyncio.sleep(3)
            continue

        try:
            await _wait_for_editor(page, timeout=30)
            if login_prompted:
                log("Login successful — chat editor is ready.")
            return
        except TimeoutError:
            if await _cloudflare_challenge_visible(page):
                await asyncio.sleep(3)
                continue
            reload_count += 1
            if reload_count == 1:
                log("ChatGPT editor not visible yet — waiting (no auto-refresh on Cloudflare).")
            elif reload_count == 5:
                log(">>> Still waiting: complete Cloudflare check or login, then wait for chat box.")
            if reload_count <= 3:
                log(f"Reloading ChatGPT ({reload_count}/3)...")
                try:
                    await page.reload()
                except Exception as exc:
                    if "closed" in str(exc).lower():
                        raise RuntimeError(
                            "Browser window was closed during login. Re-run the batch script and keep the window open."
                        ) from exc
                    raise
            else:
                await asyncio.sleep(3)
            continue

    raise TimeoutError("Timed out waiting for ChatGPT login.")


async def _start_new_chat(page: Page) -> None:
    log("Starting a new temporary chat.")
    for attempt in range(1, 4):
        await page.goto(CHATGPT_URL)
        try:
            await _wait_for_editor(page, timeout=60)
            return
        except TimeoutError:
            log(f"Temporary chat did not load (attempt {attempt}/3).")
            await asyncio.sleep(2)
    raise TimeoutError("Could not load temporary chat after retries.")


async def _select_model(page: Page, model_label: str | None = None) -> None:
    if not model_label:
        return
    log(f"Selecting model: {model_label}")
    try:
        model_btn = page.locator("button[aria-label*='model'], button:has-text('GPT')").first
        if await model_btn.is_visible():
            await model_btn.click()
            await asyncio.sleep(0.8)
            option = page.get_by_text(model_label, exact=False).first
            if await option.is_visible():
                await option.click()
                await asyncio.sleep(1)
    except Exception as exc:
        log(f"Model selection skipped or failed: {exc}")


async def _assistant_message_count(page: Page) -> int:
    return await page.locator("[data-message-author-role='assistant']").count()


async def _send_message(page: Page, text: str) -> None:
    before = await _assistant_message_count(page)
    for selector in EDITOR_SELECTORS:
        editor = page.locator(selector).first
        try:
            await editor.wait_for(state="visible", timeout=5000)
            await editor.click()
            await editor.fill(text)
            await asyncio.sleep(0.3)
            await _dismiss_rate_limit_modal(page)
            for submit in (
                "button[data-testid='send-button']",
                "button[data-testid='composer-submit-button']",
                "button[aria-label*='Send']",
                "button[aria-label*='ارسال']",
            ):
                button = page.locator(submit).first
                try:
                    if await button.is_visible() and await button.is_enabled():
                        await button.click()
                        break
                except Exception:
                    continue
            else:
                await page.keyboard.press("Enter")

            deadline = time.time() + 15
            while time.time() < deadline:
                try:
                    current_text = (await editor.inner_text()).strip()
                except Exception:
                    current_text = ""
                if not current_text or await _assistant_message_count(page) > before:
                    log("Message sent.")
                    return
                await asyncio.sleep(0.5)
            raise TimeoutError("Message did not leave the composer after send.")
        except Exception:
            continue
    raise TimeoutError("Could not find ChatGPT prompt editor to send message.")


async def _wait_until_idle(
    page: Page,
    timeout: int = 600,
    min_assistant_count: int | None = None,
) -> None:
    log("Waiting for ChatGPT response to finish...")
    deadline = time.time() + timeout
    stable_since: float | None = None
    generating_since: float | None = None
    last_text = ""
    saw_required_response = min_assistant_count is None

    while time.time() < deadline:
        if await _dismiss_rate_limit_modal(page):
            deadline += RATE_LIMIT_WAIT_SECONDS
            continue

        if min_assistant_count is not None and await _assistant_message_count(page) >= min_assistant_count:
            saw_required_response = True

        try:
            stop_btn = page.locator(STOP_BUTTON_SELECTOR).first
            is_generating = await stop_btn.is_visible()
        except Exception:
            is_generating = False

        if saw_required_response:
            if await _wait_for_assistant_download_link(page, timeout=0.5) is not None:
                return

        if is_generating:
            generating_since = generating_since or time.time()
            if (
                saw_required_response
                and generating_since
                and time.time() - generating_since >= LONG_GENERATION_STOP_SECONDS
            ):
                try:
                    await stop_btn.click()
                    log("Stopped long-running generation.")
                except Exception:
                    pass
                stop_deadline = time.time() + POST_STOP_GRACE_SECONDS
                while time.time() < stop_deadline:
                    if await _wait_for_assistant_download_link(page, timeout=0.5) is not None:
                        return
                    try:
                        if not await stop_btn.is_visible():
                            return
                    except Exception:
                        return
                    await asyncio.sleep(1)
                raise TimeoutError("Stopped long-running generation without a downloadable file.")
        else:
            generating_since = None

        body_text = await page.locator("body").inner_text()
        if saw_required_response and body_text == last_text and not is_generating:
            stable_since = stable_since or time.time()
            if time.time() - stable_since >= 8:
                return
        else:
            stable_since = None
            last_text = body_text

        await asyncio.sleep(2)

    raise TimeoutError("Timed out while waiting for ChatGPT to finish.")


async def _attach_file(page: Page, file_path: Path, native_upload: bool = False) -> None:
    file_path = file_path.resolve()
    if native_upload:
        log("native_upload=True is not implemented in Playwright migration; using DOM upload.")
    log(f"Uploading: {file_path.name}")

    file_input = page.locator("input[type='file']").first
    if await file_input.count() == 0:
        for selector in ATTACH_BUTTON_SELECTORS:
            try:
                btn = page.locator(selector).first
                if await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(0.8)
                    break
            except Exception:
                continue

    file_input = page.locator("input[type='file']").first
    await file_input.set_input_files(str(file_path))
    log("File upload initiated.")
    await asyncio.sleep(4)


async def _wait_for_file_upload_complete(page: Page, file_path: Path, timeout: int = 600) -> None:
    deadline = time.time() + timeout
    name = file_path.name[:30]
    while time.time() < deadline:
        if await _dismiss_rate_limit_modal(page):
            deadline += RATE_LIMIT_WAIT_SECONDS
            continue

        body = await page.locator("body").inner_text()
        if name in body:
            log("File upload complete.")
            return
        await asyncio.sleep(2)
    raise TimeoutError("Timed out waiting for file upload.")


async def _element_fields(element) -> tuple[str, str, str, str]:
    text = (await element.inner_text() or "").strip()
    href = await element.get_attribute("href") or ""
    title = await element.get_attribute("title") or ""
    aria = await element.get_attribute("aria-label") or ""
    return text, href, title, aria


async def _wait_for_assistant_download_link(page: Page, timeout: int = 45):
    deadline = time.time() + timeout
    while time.time() < deadline:
        assistant = page.locator("[data-message-author-role='assistant']").last
        if await assistant.count() == 0:
            await asyncio.sleep(1.0)
            continue

        ranked: list[tuple[int, object]] = []
        elements = assistant.locator("a[href], button, [role='link'], [role='button']")
        count = await elements.count()
        for index in range(count):
            element = elements.nth(index)
            try:
                if not await element.is_visible():
                    continue
                text, href, title, aria = await _element_fields(element)
                label = text or aria or title or ""
                score = score_persian_download_text(label)
                if score == 0 and is_artifact_download_trigger(text=text, href=href, title=title, aria=aria):
                    score = 40
                if score > 0:
                    ranked.append((score, element))
            except Exception:
                continue

        if ranked:
            ranked.sort(key=lambda item: item[0], reverse=True)
            return ranked[0][1]
        await asyncio.sleep(1.0)
    return None


async def _click_candidate_and_wait(page: Page, element, before: set[Path]) -> Path | None:
    text, href, title, aria = await _element_fields(element)
    if not is_artifact_download_trigger(text=text, href=href, title=title, aria=aria):
        return None

    label = (text or aria or title or href or "")[:120]
    log(f"Clicking artifact download candidate: {label!r}")
    await element.scroll_into_view_if_needed()
    await asyncio.sleep(0.4)
    await _dismiss_rate_limit_modal(page)
    await element.click()
    deadline = time.time() + 45
    while time.time() < deadline:
        downloaded = wait_for_download_settled(before, timeout=3)
        if downloaded:
            log(f"Download detected after click: {downloaded.name}")
            return downloaded
        await asyncio.sleep(0.8)
    return None


async def _click_new_download_link(page: Page, before: set[Path]) -> Path | None:
    element = await _wait_for_assistant_download_link(page, timeout=45)
    if element is not None:
        text, href, title, aria = await _element_fields(element)
        label = (text or aria or title or href or "")[:120]
        log(f"Clicking download candidate: {label!r}")
        await element.scroll_into_view_if_needed()
        await asyncio.sleep(0.5)
        await _dismiss_rate_limit_modal(page)
        await element.click()
        deadline = time.time() + 60
        while time.time() < deadline:
            downloaded = wait_for_download_settled(before, timeout=3)
            if downloaded:
                log(f"Download detected after click: {downloaded.name}")
                return downloaded
            await asyncio.sleep(1.0)

    assistants = page.locator("[data-message-author-role='assistant']")
    count = await assistants.count()
    for assistant_index in range(count - 1, -1, -1):
        assistant = assistants.nth(assistant_index)
        elements = assistant.locator("a[href], button, [role='link'], [role='button']")
        element_count = await elements.count()
        for element_index in range(element_count - 1, -1, -1):
            element = elements.nth(element_index)
            try:
                if not await element.is_visible():
                    continue
                downloaded = await _click_candidate_and_wait(page, element, before)
                if downloaded:
                    return downloaded
            except Exception:
                continue
    return None


async def _latest_assistant_text(page: Page) -> str:
    selectors = [
        "[data-message-author-role='assistant']",
        "article",
        "main .markdown",
    ]
    for selector in selectors:
        locator = page.locator(selector)
        if await locator.count() > 0:
            text = (await locator.last.inner_text()).strip()
            if text:
                return text
    return (await page.locator("body").inner_text()).strip()


def safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")


def start_new_chat(driver: PlaywrightDriver) -> None:
    _run(_start_new_chat(driver.page))


def select_model(driver: PlaywrightDriver, model_label: str | None = None) -> None:
    _run(_select_model(driver.page, model_label))


def assistant_message_count(driver: PlaywrightDriver) -> int:
    return _run(_assistant_message_count(driver.page))


def send_message(driver: PlaywrightDriver, text: str) -> None:
    _run(_send_message(driver.page, text))


def wait_until_idle(
    driver: PlaywrightDriver,
    timeout: int = 600,
    min_assistant_count: int | None = None,
) -> None:
    _run(_wait_until_idle(driver.page, timeout=timeout, min_assistant_count=min_assistant_count))


def attach_file(driver: PlaywrightDriver, file_path: Path, native_upload: bool = False) -> None:
    _run(_attach_file(driver.page, file_path, native_upload=native_upload))


def wait_for_file_upload_complete(driver: PlaywrightDriver, file_path: Path, timeout: int = 600) -> None:
    _run(_wait_for_file_upload_complete(driver.page, file_path, timeout=timeout))


def wait_until_logged_in(driver: PlaywrightDriver, timeout: int = 600) -> None:
    _run(_wait_until_logged_in(driver.page, timeout=timeout, headless=driver._headless))


def latest_assistant_text(driver: PlaywrightDriver) -> str:
    return _run(_latest_assistant_text(driver.page))


def resolve_download(
    driver: PlaywrightDriver | None,
    before: set[Path],
    *,
    timeout: int = 90,
    click: bool = True,
) -> Path | None:
    downloaded = None
    if click and driver is not None:
        downloaded = _run(_click_new_download_link(driver.page, before))
        if downloaded is None:
            log("First download click pass missed; retrying download element scan...")
            time.sleep(2)
            downloaded = _run(_click_new_download_link(driver.page, before))
    if downloaded is None:
        downloaded = wait_and_salvage_download(before, timeout=timeout)
    if downloaded is None:
        candidates = find_opml_candidates_in_downloads(before)
        if candidates:
            downloaded = candidates[0]
            log(f"Salvaged file from downloads/: {downloaded.name}")
    return downloaded


async def run_async(
    prompt_path: Path,
    file_path: Path,
    headless: bool = False,
    model: str | None = None,
) -> int:
    LOG_FILE.write_text("", encoding="utf-8")
    if not prompt_path.exists() or not file_path.exists():
        raise FileNotFoundError("Prompt or input file missing.")

    prompt = prompt_path.read_text(encoding="utf-8").strip()
    driver = build_driver(headless=headless)

    try:
        driver.get(CHATGPT_URL)
        wait_until_logged_in(driver)
        start_new_chat(driver)
        if model:
            select_model(driver, model)

        before_downloads = set(DOWNLOAD_DIR.glob("*"))
        attach_file(driver, file_path)
        wait_for_file_upload_complete(driver, file_path)

        expected_assistant_count = assistant_message_count(driver) + 1
        send_message(driver, prompt)
        wait_until_idle(driver, min_assistant_count=expected_assistant_count)

        downloaded = resolve_download(driver, before_downloads, timeout=90)
        response_text = latest_assistant_text(driver)
        TEXT_OUTPUT.write_text(response_text, encoding="utf-8")
        driver.save_screenshot(str(SCREENSHOT))

        if downloaded:
            final = ROOT / f"{safe_filename(file_path.stem)}.opml"
            if final.exists():
                final.unlink()
            downloaded.replace(final)
            log(f"Downloaded: {final}")
        else:
            log("No download detected. Check downloads/ folder.")

        return 0
    finally:
        log("Leaving browser open 15 seconds for inspection...")
        time.sleep(15)
        driver.quit()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    try:
        return _run(run_async(args.prompt, args.file, args.headless, args.model))
    except Exception as exc:
        log(f"ERROR: {exc}")
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())