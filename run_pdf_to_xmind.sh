#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "=== PDF/DOCX -> OPML -> XMind Pipeline v3 (Linux) ==="
echo "Project dir: $(pwd)"
echo ""
echo "First run: script auto-opens real Chromium for Google login, then continues."

VENV_DIR=".venv-linux"
PYTHON="${VENV_DIR}/bin/python"

if [[ ! -x "${PYTHON}" ]]; then
  ./setup.sh
fi

if ! "${PYTHON}" -c "import patchright, playwright_stealth" 2>/dev/null; then
  "${PYTHON}" -m pip install --upgrade pip
  "${PYTHON}" -m pip install -r requirements.txt
  "${PYTHON}" -m patchright install chromium
fi

INPUT_DIR="${INPUT_DIR:-inputs}"
OPML_DIR="${OPML_DIR:-outputs/opml}"
XMIND_DIR="${XMIND_DIR:-outputs/xmind}"
PROMPT_FILE="${PROMPT_FILE:-prompts/prompt-mind-map.md}"
RESPONSE_TIMEOUT="${RESPONSE_TIMEOUT:-600}"
DOWNLOAD_TIMEOUT="${DOWNLOAD_TIMEOUT:-120}"
SKIP_WARMUP="${SKIP_WARMUP:-1}"
export LONG_GENERATION_STOP_SECONDS="${LONG_GENERATION_STOP_SECONDS:-900}"
export POST_STOP_GRACE_SECONDS="${POST_STOP_GRACE_SECONDS:-60}"

echo ""
echo "Input dir : ${INPUT_DIR}"
echo "OPML dir  : ${OPML_DIR}  (intermediate)"
echo "XMind dir : ${XMIND_DIR}  (final output)"
echo "Prompt    : ${PROMPT_FILE}"
echo ""

ARGS=(
  --input-dir "${INPUT_DIR}"
  --opml-dir "${OPML_DIR}"
  --xmind-dir "${XMIND_DIR}"
  --prompt "${PROMPT_FILE}"
  --response-timeout "${RESPONSE_TIMEOUT}"
  --download-timeout "${DOWNLOAD_TIMEOUT}"
)
if [[ "${SKIP_WARMUP}" == "1" ]]; then
  ARGS+=(--no-warm-up)
fi

"${PYTHON}" scripts/pipeline.py pdf "${ARGS[@]}" "$@"

EXIT_CODE=$?
echo ""
echo "Pipeline finished with exit code: ${EXIT_CODE}"
echo "Final XMind files: ${XMIND_DIR}/"
exit $EXIT_CODE