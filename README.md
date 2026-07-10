# ChatGPT Mind Map → XMind

The canonical end-to-end automation pipeline for turning study materials into **XMind mind maps** (`.xmind`) through the ChatGPT web UI.

> Repository consolidation: this project is the successor formerly named `chatgpt-mindmap-to-xmind-v3`. It supersedes `chatgpt-mindmap-to-xmind`, `chatgpt-mindmap-to-xmind-v2`, `chatgpt-mindmap-pipeline`, and `chatgpt-mindmap-automation`.

```
PDF / DOCX / Markdown / TeX  →  ChatGPT (OPML)  →  XMind (.xmind)
```

## Why this is the canonical version

- **Patchright/Playwright** browser automation with stealth, replacing the older Selenium implementation
- **Parallel batch workers** with file locks, isolated download folders, and separate Chrome profiles
- **High-yield oral-exam prompt** with mandatory concept consolidation and `🎯 Oral Exam High-Yield` branches
- Long-generation stopping, download salvage, rate-limit handling, network recovery, and per-worker environment isolation
- Reliability fixes consolidated from the optimized pipeline: retries, browser recreation, OPML repair and validation, index-file filtering, and machine-readable batch summaries

| Mode | Input | Intermediate | Final output |
|------|-------|--------------|--------------|
| **PDF batch** | Folder of `.pdf`, `.docx`, `.md`, or `.tex` files | `outputs/opml/` | `outputs/xmind/*.xmind` |
| **Markdown** | One `.md` file split by `##` headings | `outputs/opml/` | `outputs/xmind/*.xmind` |

## Requirements

- Python 3.10+
- Chromium, installed automatically through Patchright
- ChatGPT account; log in once and reuse the saved profile in `chrome_profile/`
- Linux recommended; parallel batch mode is tested on Linux

## Quick Start

### Setup once

```bash
cd chatgpt-mindmap-to-xmind
chmod +x setup.sh run_pdf_to_xmind.sh run_md_to_xmind.sh run_parallel_batch.sh
./setup.sh
```

On the first run, the project opens a real Chromium session for login and then reuses that authenticated profile for automation.

### PDF / DOCX / Markdown / TeX → XMind

```bash
# Put source files in inputs/, then:
./run_pdf_to_xmind.sh --overwrite

# Custom paths
INPUT_DIR=/path/to/files \
OPML_DIR=/path/to/opml \
XMIND_DIR=/path/to/xmind \
./run_pdf_to_xmind.sh --limit 3 --overwrite
```

### Markdown sections → XMind

```bash
MARKDOWN_FILE=/path/to/notes.md ./run_md_to_xmind.sh --overwrite

# Specific sections only
MARKDOWN_FILE=/path/to/notes.md ./run_md_to_xmind.sh --sections 1,3,5-8 --overwrite
```

### Parallel PDF batch

Split a large input folder across two isolated ChatGPT sessions:

```bash
# Worker 1: files 1-10, worker 2: files 11-20
START1=1 END1=10 START2=11 END2=20 ./run_parallel_batch.sh

# Convert all generated OPML to XMind
OPML_DIR=outputs/opml XMIND_DIR=outputs/xmind ./run_opml_to_xmind.sh --overwrite
```

Each worker uses its own browser profile, download folder, and log file. Locks in `outputs/opml/.locks/` prevent duplicate work, and stale locks are reclaimed automatically.

### OPML → XMind only

```bash
OPML_DIR=outputs/opml XMIND_DIR=outputs/xmind ./run_opml_to_xmind.sh --overwrite
```

## Reliability and recovery

The reliability layer originally documented in `chatgpt-mindmap-pipeline` is included here and extended for Playwright:

| Failure mode | Current behavior |
|--------------|------------------|
| No downloadable OPML appears | Up to 3 attempts by default, with fresh-chat recovery between attempts |
| Download link renders late or the first click misses | Multi-pass link detection, delayed click retries, sandbox-link fallback, and download salvage |
| Chromium leaves a partial `.crdownload` | Waits for the download set to settle before accepting the file |
| Browser crashes, disconnects, or returns protocol errors | Detects the dead session, clears profile locks, recreates the browser, and restores login state |
| Network drops mid-run | Waits for connectivity before recreating the session and retrying |
| Temporary-chat cookies accumulate | Prunes automation cookies while preserving the authenticated login session |
| ChatGPT produces malformed OPML XML | Repairs and validates OPML before saving and again before XMind conversion |
| Index or README inputs are mixed into a batch | Skips `00_INDEX*`, `INDEX`, and `README` inputs automatically |
| A batch partially fails | Continues converting successful OPML files and writes `logs/last_batch_summary.json` |
| Parallel workers select the same item | Per-output file locks prevent duplicate processing |

The shell runners use conservative defaults for long generations:

- Response timeout: **900 seconds**
- Download timeout: **150 seconds**
- Long-generation stop: **900 seconds**
- Post-stop grace period: **60 seconds**

Override them with `RESPONSE_TIMEOUT`, `DOWNLOAD_TIMEOUT`, `LONG_GENERATION_STOP_SECONDS`, and `POST_STOP_GRACE_SECONDS`.

## Project structure

```
chatgpt-mindmap-to-xmind/
├── README.md
├── CONSOLIDATION.md
├── requirements.txt
├── setup.sh
├── run_pdf_to_xmind.sh          # Full file pipeline → .xmind
├── run_md_to_xmind.sh           # Full Markdown pipeline → .xmind
├── run_parallel_batch.sh        # Two-worker parallel OPML generation
├── run_pdf_batch.sh / run_md_batch.sh
├── prompts/prompt-mind-map.md   # Oral-exam high-yield prompt
├── scripts/
│   ├── pipeline.py
│   ├── run_chatgpt_temporary_test.py   # Patchright / Playwright core
│   ├── batch_common.py                 # retries, recovery, repair, summaries
│   ├── batch_pdf.py                    # file batch + locks + parallel ranges
│   ├── batch_markdown.py               # Markdown ## sections → OPML
│   ├── opml_utils.py                   # OPML repair and validation
│   ├── smoke_test_playwright.py
│   └── convert_opml_to_xmind.py
├── inputs/
├── outputs/
│   ├── opml/
│   └── xmind/
├── downloads/
├── logs/
└── chrome_profile/
```

## CLI options

| Flag | Description |
|------|-------------|
| `--overwrite` | Regenerate existing OPML and XMind files |
| `--limit N` | Process only the first N files or sections |
| `--start-index N` / `--end-index N` | Select a 1-based file or section range for parallel workers |
| `--model "Name"` | Select a ChatGPT model label |
| `--max-attempts N` | Retries per file; default 3 |
| `--max-section-attempts N` | Retries per Markdown section; default 3 |
| `--save-diagnostics` | Save response text and a screenshot per failed item |
| `--response-timeout SEC` | Maximum ChatGPT response wait |
| `--download-timeout SEC` | Maximum OPML download wait |
| `--no-warm-up` | Skip the initial hello warm-up message |
| `--keep-browser` | Leave the browser open after the batch finishes |

## Outputs and logs

```
outputs/
├── opml/                   # repaired and validated intermediate files
└── xmind/                  # final XMind files
logs/
├── last_batch_summary.json # successes, failures, mode, paths, and timeouts
└── *.log                   # session or per-worker logs
```

A batch exit code of `0` means all selected items succeeded, `2` means the batch completed with one or more item failures, and `1` indicates a setup or invocation error.

## Customizing the prompt

Edit `prompts/prompt-mind-map.md`. The default prompt targets oral-exam preparation with a high-yield filter, concept consolidation, and `🎯 Oral Exam High-Yield` branches. Keep the requirement that ChatGPT outputs a **downloadable `.opml` file**.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Chromium not installed | Re-run `./setup.sh`; it runs `patchright install chromium` |
| Not logged in | Complete login in the real Chromium window opened on first run |
| No OPML downloaded | Use `--save-diagnostics`; inspect `downloads/`, the response text, and screenshot |
| Parallel workers clash | Confirm that each worker has a distinct `CHATGPT_CHROME_PROFILE_DIR` and download folder |
| `Could not load temporary chat` | Run `python3 scripts/prune_chatgpt_cookies.py`; login cookies are preserved |
| Browser crashes or disconnects repeatedly | Check the network, clear stale Chromium processes, and rerun; the batch will recreate its session |
| Smoke test | Run `python3 scripts/smoke_test_playwright.py` |

## Repository consolidation

See `CONSOLIDATION.md` for the source-repository audit, duplicate evidence, reliability comparison, and the safe rename/archive order.

## Related projects

- [macwili](https://github.com/alifazelidehkordi/macwili) — source of Playwright browser logic and the parallel batch pattern
- `qa-mindmap-to-xmind` — NotebookLM Q&A → XMind workflow
