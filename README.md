# ChatGPT Mind Map → XMind Pipeline (v3)

End-to-end automation: turn study materials into **XMind mind maps** (`.xmind`) using the ChatGPT web UI.

**v3 upgrades** (from macwili + oral-exam prompt):
- **Patchright/Playwright** browser automation with stealth (replaces Selenium)
- **Parallel batch workers** with file locks and separate Chrome profiles
- **High-yield oral exam prompt** with mandatory concept consolidation and `🎯 Oral Exam High-Yield` branches
- Long-generation stop, download salvage, rate-limit handling, and per-worker env isolation

```
PDF / DOCX / Markdown  →  ChatGPT (OPML)  →  XMind (.xmind)
```

| Mode | Input | Intermediate | Final output |
|------|-------|--------------|--------------|
| **PDF** | Folder of `.pdf` / `.docx` / `.md` | `outputs/opml/` | `outputs/xmind/*.xmind` |
| **Markdown** | One `.md` with `##` sections | `outputs/opml/` | `outputs/xmind/*.xmind` |

## Requirements

- Python 3.10+
- Chromium (installed automatically via Patchright)
- ChatGPT account (login once; saved in `chrome_profile/`)
- Linux recommended (parallel batch tested on Linux)

## Quick Start

### Setup (once)

```bash
cd chatgpt-mindmap-to-xmind-v3
chmod +x setup.sh run_pdf_to_xmind.sh run_md_to_xmind.sh run_parallel_batch.sh
./setup.sh
```

Log in when the browser opens on the first batch run.

### PDF → XMind

```bash
# Put PDFs in inputs/, then:
./run_pdf_to_xmind.sh --overwrite

# Custom paths
INPUT_DIR=/path/to/pdfs \
OPML_DIR=/path/to/opml \
XMIND_DIR=/path/to/xmind \
./run_pdf_to_xmind.sh --limit 3 --overwrite
```

### Markdown → XMind

```bash
MARKDOWN_FILE=/path/to/notes.md ./run_md_to_xmind.sh --overwrite

# Specific sections only
MARKDOWN_FILE=/path/to/notes.md ./run_md_to_xmind.sh --sections 1,3,5-8 --overwrite
```

### Parallel PDF batch (2 workers)

Split a large `inputs/` folder across two ChatGPT sessions:

```bash
# Worker 1: files 1-10, Worker 2: files 11-20
START1=1 END1=10 START2=11 END2=20 ./run_parallel_batch.sh

# Then convert all OPML to XMind
OPML_DIR=outputs/opml XMIND_DIR=outputs/xmind ./run_opml_to_xmind.sh --overwrite
```

Each worker uses its own `chrome_profile`, `downloads/` folder, and log file. File locks in `outputs/opml/.locks/` prevent duplicate work.

### OPML → XMind only

```bash
OPML_DIR=outputs/opml XMIND_DIR=outputs/xmind ./run_opml_to_xmind.sh --overwrite
```

## Project Structure

```
chatgpt-mindmap-to-xmind-v3/
├── README.md
├── requirements.txt
├── setup.sh
├── run_pdf_to_xmind.sh          # Full PDF pipeline → .xmind
├── run_md_to_xmind.sh           # Full Markdown pipeline → .xmind
├── run_parallel_batch.sh        # 2-worker parallel OPML generation
├── run_pdf_batch.sh / run_md_batch.sh
├── prompts/prompt-mind-map.md   # v3 oral-exam high-yield prompt
├── scripts/
│   ├── pipeline.py
│   ├── run_chatgpt_temporary_test.py   # Patchright / Playwright core
│   ├── batch_pdf.py                    # PDF/DOCX → OPML (locks + parallel)
│   ├── batch_markdown.py               # Markdown ## → OPML
│   ├── smoke_test_playwright.py
│   └── convert_opml_to_xmind.py
├── inputs/
├── outputs/
│   ├── opml/
│   └── xmind/
├── downloads/
└── chrome_profile/
```

## CLI Options

| Flag | Description |
|------|-------------|
| `--overwrite` | Re-generate existing OPML and XMind files |
| `--limit N` | Process only first N files/sections |
| `--start-index N` / `--end-index N` | 1-based file/section range (for parallel workers) |
| `--model "Name"` | ChatGPT model label |
| `--save-diagnostics` | Save response text + screenshot per item |
| `--response-timeout SEC` | Max wait for ChatGPT response (default 600) |
| `--download-timeout SEC` | Max wait for OPML download (default 90–120) |
| `--no-warm-up` | Skip the initial hello warm-up message |
| `--keep-browser` | Leave browser open after batch finishes |

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `CHATGPT_CHROME_PROFILE_DIR` | Per-worker browser profile path |
| `CHATGPT_DOWNLOAD_DIR` | Per-worker download staging folder |
| `CHATGPT_RUN_LOG` | Per-worker log file path |
| `LONG_GENERATION_STOP_SECONDS` | Auto-stop runaway generation (default 900) |
| `POST_STOP_GRACE_SECONDS` | Grace period after stop (default 60) |
| `SKIP_WARMUP=1` | Default in shell scripts — skips hello warm-up |

## Customizing the Prompt

Edit `prompts/prompt-mind-map.md`. The v3 prompt targets **oral exam prep**: high-yield filter, concept consolidation, and `🎯 Oral Exam High-Yield` sub-branches. Keep the requirement that ChatGPT outputs a **downloadable `.opml` file**.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Chromium not installed | Re-run `./setup.sh` (runs `patchright install chromium`) |
| Not logged in | Log in manually in the opened browser |
| No OPML downloaded | Use `--save-diagnostics`; check `downloads/` |
| Parallel workers clash | Ensure different `CHATGPT_CHROME_PROFILE_DIR` per worker (see `run_parallel_batch.sh`) |
| `Could not load temporary chat` | Run `python3 scripts/prune_chatgpt_cookies.py` (login preserved) |
| Smoke test | `python3 scripts/smoke_test_playwright.py` |

## Related Projects

- [macwili](https://github.com/alifazelidehkordi/macwili) — source of Playwright browser logic and parallel batch pattern
- `qa-mindmap-to-xmind` — NotebookLM Q&A → XMind workflow