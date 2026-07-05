from __future__ import annotations

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import batch_common as common
import run_chatgpt_temporary_test as core


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "opml"
DEFAULT_PROMPT = ROOT / "prompts" / "prompt-mind-map.md"
LOCK_STALE_SECONDS = int(os.environ.get("BATCH_LOCK_STALE_SECONDS", "21600"))


@dataclass(frozen=True)
class MarkdownSection:
    index: int
    title: str
    text: str

    @property
    def output_stem(self) -> str:
        return f"{self.index:02d}_{core.safe_filename(self.title).lower()}"


def batch_log(message: str) -> None:
    common.batch_log(message)


def acquire_output_lock(output_path: Path) -> Path | None:
    lock_dir = output_path.parent / ".locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / f"{output_path.name}.lock"
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(lock_path, flags)
    except FileExistsError:
        if time.time() - lock_path.stat().st_mtime <= LOCK_STALE_SECONDS:
            return None
        lock_path.unlink(missing_ok=True)
        try:
            fd = os.open(lock_path, flags)
        except FileExistsError:
            return None
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(f"pid={os.getpid()} time={int(time.time())}\n")
    return lock_path


def release_output_lock(lock_path: Path | None) -> None:
    if lock_path is not None:
        lock_path.unlink(missing_ok=True)


def parse_section_numbers(value: str | None) -> set[int] | None:
    if not value:
        return None

    selected: set[int] = set()
    for raw_part in value.split(","):
        part = raw_part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start = int(start_text.strip())
            end = int(end_text.strip())
            if start <= 0 or end <= 0 or end < start:
                raise ValueError(f"Invalid section range: {part}")
            selected.update(range(start, end + 1))
        else:
            section = int(part)
            if section <= 0:
                raise ValueError(f"Invalid section number: {part}")
            selected.add(section)
    return selected


def split_markdown_sections(markdown_path: Path) -> list[MarkdownSection]:
    text = markdown_path.read_text(encoding="utf-8")
    heading_pattern = re.compile(r"(?m)^##\s+(.+?)\s*$")
    matches = list(heading_pattern.finditer(text))
    sections: list[MarkdownSection] = []

    for zero_index, match in enumerate(matches):
        start = match.start()
        end = matches[zero_index + 1].start() if zero_index + 1 < len(matches) else len(text)
        title = match.group(1).strip()
        section_text = text[start:end].strip()
        if title and section_text:
            sections.append(MarkdownSection(index=len(sections) + 1, title=title, text=section_text))

    return sections


def select_sections(
    sections: list[MarkdownSection],
    sections_filter: set[int] | None,
    limit: int | None,
    start_index: int | None = None,
    end_index: int | None = None,
) -> list[MarkdownSection]:
    if sections_filter is not None:
        sections = [section for section in sections if section.index in sections_filter]
    if start_index is not None or end_index is not None:
        start = 1 if start_index is None else start_index
        end = max(section.index for section in sections) if end_index is None else end_index
        sections = [section for section in sections if start <= section.index <= end]
    if limit is not None:
        sections = sections[:limit]
    return sections


def write_markdown_section_file(section: MarkdownSection, section_dir: Path) -> Path:
    section_dir.mkdir(parents=True, exist_ok=True)
    section_path = section_dir / f"{section.output_stem}.md"
    section_path.write_text(section.text.rstrip() + "\n", encoding="utf-8")
    return section_path


def build_section_prompt(prompt: str, section: MarkdownSection) -> str:
    return (
        f"{prompt}\n\n"
        "Use the uploaded Markdown file as the complete source text. "
        f"It contains section {section.index}: {section.title}. "
        "Create the downloadable OPML file from only that uploaded Markdown file."
    )


def process_markdown_section(
    driver,
    prompt: str,
    section: MarkdownSection,
    section_file: Path,
    output_dir: Path,
    model: str | None,
    download_timeout: int,
    response_timeout: int,
    save_diagnostics: bool,
) -> bool:
    output_path = output_dir / f"{section.output_stem}.opml"
    batch_log(f"Processing section {section.index}: {section.title}")

    core.start_new_chat(driver)
    if model:
        core.select_model(driver, model)

    before_downloads = set(core.DOWNLOAD_DIR.glob("*"))
    core.attach_file(driver, section_file, native_upload=False)
    core.wait_for_file_upload_complete(driver, section_file)

    expected_assistant_count = core.assistant_message_count(driver) + 1
    core.send_message(driver, build_section_prompt(prompt, section))
    core.wait_until_idle(
        driver,
        timeout=response_timeout,
        min_assistant_count=expected_assistant_count,
    )

    time.sleep(2)
    downloaded = core.resolve_download(driver, before_downloads, timeout=download_timeout)
    if downloaded is None:
        batch_log("Retrying download click after link render wait...")
        time.sleep(5)
        downloaded = core.resolve_download(driver, before_downloads, timeout=download_timeout)

    if save_diagnostics:
        response_text = core.latest_assistant_text(driver)
        (output_dir / f"{section.output_stem}.last_response.txt").write_text(
            response_text,
            encoding="utf-8",
        )
        driver.save_screenshot(str(output_dir / f"{section.output_stem}.last_state.png"))

    if downloaded is None:
        batch_log(f"FAILED: no downloadable OPML detected for section {section.index}: {section.title}")
        return False

    common.save_artifact_download(downloaded, output_path)
    batch_log(f"Saved OPML: {output_path}")
    return True


def run_batch(
    markdown_file: Path,
    output_dir: Path,
    prompt_path: Path,
    sections_filter: set[int] | None = None,
    overwrite: bool = False,
    limit: int | None = None,
    model: str | None = None,
    save_diagnostics: bool = False,
    max_section_attempts: int = 3,
    download_timeout: int = 90,
    response_timeout: int = 600,
    close_delay: int = 20,
    chrome_profile_dir: Path | None = None,
    skip_warmup: bool = False,
    keep_browser: bool = False,
    start_index: int | None = None,
    end_index: int | None = None,
) -> int:
    core.LOG_FILE.write_text("", encoding="utf-8")
    output_dir.mkdir(parents=True, exist_ok=True)

    if chrome_profile_dir is not None:
        os.environ["CHATGPT_CHROME_PROFILE_DIR"] = str(chrome_profile_dir)

    if not markdown_file.exists():
        raise FileNotFoundError(markdown_file)
    if not prompt_path.exists():
        raise FileNotFoundError(prompt_path)

    prompt = prompt_path.read_text(encoding="utf-8").strip()
    if not prompt:
        raise ValueError("Prompt file is empty.")

    all_sections = split_markdown_sections(markdown_file)
    sections = select_sections(
        all_sections,
        sections_filter,
        limit,
        start_index=start_index,
        end_index=end_index,
    )
    if not sections:
        batch_log(f"No matching level-2 Markdown sections found in {markdown_file}")
        return 1

    section_dir = output_dir / "_md_sections"
    batch_log(f"Markdown file: {markdown_file}")
    batch_log(f"Output folder: {output_dir}")
    batch_log(f"Detected sections: {len(all_sections)}")
    batch_log(f"Sections to process: {len(sections)}")
    batch_log(f"Download timeout: {download_timeout}s")
    batch_log(f"Response timeout: {response_timeout}s")

    driver = common.bootstrap_session(model, skip_warmup=skip_warmup)
    successes = 0
    failures: list[str] = []
    try:
        for position, section in enumerate(sections, start=1):
            output_path = output_dir / f"{section.output_stem}.opml"
            if output_path.exists() and not overwrite:
                batch_log(f"Skipping existing ({position}/{len(sections)}): {output_path.name}")
                successes += 1
                continue

            lock_path = acquire_output_lock(output_path)
            if lock_path is None:
                batch_log(
                    f"Skipping claimed by another worker ({position}/{len(sections)}): {output_path.name}"
                )
                successes += 1
                continue

            batch_log(f"Starting section {section.index} ({position}/{len(sections)})")
            section_file = write_markdown_section_file(section, section_dir)

            def attempt(driver_obj):
                return process_markdown_section(
                    driver=driver_obj,
                    prompt=prompt,
                    section=section,
                    section_file=section_file,
                    output_dir=output_dir,
                    model=model,
                    download_timeout=download_timeout,
                    response_timeout=response_timeout,
                    save_diagnostics=save_diagnostics,
                )

            label = f"section {section.index:02d} {section.title}"
            try:
                ok, driver = common.run_with_retries(
                    label,
                    driver,
                    model,
                    attempt,
                    max_attempts=max_section_attempts,
                    skip_warmup=skip_warmup,
                )
            finally:
                release_output_lock(lock_path)
            if ok:
                successes += 1
            else:
                failures.append(f"{section.index:02d} {section.title}")
            common.prune_driver_cookies(driver)

        batch_log(f"Markdown batch complete. Successes: {successes}. Failures: {len(failures)}.")
        if failures:
            batch_log("Failed sections:")
            for name in failures:
                batch_log(f"- {name}")

        common.write_batch_summary(
            mode="markdown-opml",
            successes=successes,
            failures=failures,
            output_dir=output_dir,
            extra={
                "markdown_file": str(markdown_file),
                "max_section_attempts": max_section_attempts,
                "download_timeout": download_timeout,
                "response_timeout": response_timeout,
            },
        )
        return 0 if not failures else 2
    finally:
        if keep_browser:
            batch_log("Keeping browser open (--keep-browser).")
        else:
            batch_log(f"Closing browser in {close_delay} seconds...")
            time.sleep(close_delay)
            common.quit_driver(driver)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert each ## section in a Markdown file into an OPML mind map."
    )
    parser.add_argument("--markdown-file", type=Path, required=True, help="Markdown file with ## section headings")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    parser.add_argument("--sections", default=None, help="Comma-separated section numbers or ranges, e.g. 20,21,22 or 20-22.")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--model", default=None)
    parser.add_argument("--save-diagnostics", action="store_true")
    parser.add_argument("--max-section-attempts", type=int, default=3)
    parser.add_argument("--download-timeout", type=int, default=90)
    parser.add_argument("--response-timeout", type=int, default=600)
    parser.add_argument("--close-delay", type=int, default=20)
    parser.add_argument("--chrome-profile-dir", type=Path, default=None)
    parser.add_argument("--start-index", type=int, help="1-based first section index to process")
    parser.add_argument("--end-index", type=int, help="1-based last section index to process")
    parser.add_argument(
        "--no-warm-up",
        action="store_true",
        help="Skip the initial hello warm-up message when opening ChatGPT.",
    )
    parser.add_argument(
        "--keep-browser",
        action="store_true",
        help="Do not close the browser when the batch finishes.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        return run_batch(
            markdown_file=args.markdown_file,
            output_dir=args.output_dir,
            prompt_path=args.prompt,
            sections_filter=parse_section_numbers(args.sections),
            overwrite=args.overwrite,
            limit=args.limit,
            model=args.model,
            save_diagnostics=args.save_diagnostics,
            max_section_attempts=args.max_section_attempts,
            download_timeout=args.download_timeout,
            response_timeout=args.response_timeout,
            close_delay=args.close_delay,
            chrome_profile_dir=args.chrome_profile_dir,
            skip_warmup=args.no_warm_up,
            keep_browser=args.keep_browser,
            start_index=args.start_index,
            end_index=args.end_index,
        )
    except Exception as exc:
        core.log(f"ERROR: {exc}")
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
