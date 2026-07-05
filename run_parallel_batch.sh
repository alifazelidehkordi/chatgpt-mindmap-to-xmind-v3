#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

INPUT_DIR="${INPUT_DIR:-inputs}"
START1="${START1:-1}"
END1="${END1:-16}"
START2="${START2:-17}"
END2="${END2:-32}"
STAGGER_SECONDS="${STAGGER_SECONDS:-90}"
READY_TIMEOUT="${READY_TIMEOUT:-300}"

PYTHON="${PWD}/.venv-linux/bin/python"
export PYTHONPATH="${PWD}/scripts"

mkdir -p logs downloads downloads_worker2 chrome_profile_worker2 outputs/opml/.locks
chmod +x run_opml_to_xmind.sh run_pdf_batch.sh 2>/dev/null || true

echo "=== Mind Map v3 Parallel Batch: 2 workers ==="
echo "Input     : ${INPUT_DIR}"
echo "worker1   : files ${START1}-${END1} -> logs/batch_run_worker1.log"
echo "worker2   : files ${START2}-${END2} -> logs/batch_run_worker2.log"
echo "stagger   : ${STAGGER_SECONDS}s minimum; worker2 waits for worker1 login"
echo ""

cleanup() {
  local code=$?
  if [[ -n "${pid1:-}" ]] && kill -0 "$pid1" 2>/dev/null; then kill "$pid1" 2>/dev/null || true; fi
  if [[ -n "${pid2:-}" ]] && kill -0 "$pid2" 2>/dev/null; then kill "$pid2" 2>/dev/null || true; fi
  exit "$code"
}
trap cleanup EXIT INT TERM

echo "Step 0: ensure login on main profile (real Chromium if needed)..."
"${PYTHON}" scripts/prepare_parallel.py chrome_profile_worker2

rm -f outputs/opml/.locks/*.lock chrome_profile/SingletonLock chrome_profile_worker2/SingletonLock 2>/dev/null || true

: > logs/batch_run_worker1.log
: > logs/batch_run_worker2.log

INPUT_DIR="${INPUT_DIR}" \
CHATGPT_DOWNLOAD_DIR="$PWD/downloads" \
CHATGPT_RUN_LOG="$PWD/run_worker1.log" \
CHATGPT_SKIP_REAL_CHROME_LOGIN=1 \
./run_pdf_batch.sh --save-diagnostics --start-index "$START1" --end-index "$END1" \
  >> logs/batch_run_worker1.log 2>&1 &
pid1=$!

echo "Worker1 started (pid ${pid1}). Waiting for login before worker2..."
ready=0
deadline=$((SECONDS + READY_TIMEOUT))
while (( SECONDS < deadline )); do
  if grep -q "Logged-in chat box is visible\|Starting file" logs/batch_run_worker1.log 2>/dev/null; then
    ready=1
    break
  fi
  if ! kill -0 "$pid1" 2>/dev/null; then
    echo "Worker1 exited early. See logs/batch_run_worker1.log"
    wait "$pid1" || true
    exit 1
  fi
  sleep 5
done

if (( ready == 0 )); then
  echo "Worker1 not ready after ${READY_TIMEOUT}s — aborting before starting worker2."
  kill "$pid1" 2>/dev/null || true
  wait "$pid1" 2>/dev/null || true
  exit 1
fi

echo "Worker1 ready. Sleeping ${STAGGER_SECONDS}s before worker2..."
sleep "$STAGGER_SECONDS"

"${PYTHON}" scripts/prepare_parallel.py --sync-only chrome_profile_worker2

INPUT_DIR="${INPUT_DIR}" \
CHATGPT_CHROME_PROFILE_DIR="$PWD/chrome_profile_worker2" \
CHATGPT_SYNC_PROFILE_FROM="$PWD/chrome_profile" \
CHATGPT_DOWNLOAD_DIR="$PWD/downloads_worker2" \
CHATGPT_RUN_LOG="$PWD/run_worker2.log" \
CHATGPT_SKIP_REAL_CHROME_LOGIN=1 \
CHATGPT_SKIP_COOKIE_PRUNE=1 \
./run_pdf_batch.sh --save-diagnostics --start-index "$START2" --end-index "$END2" \
  >> logs/batch_run_worker2.log 2>&1 &
pid2=$!

echo "Worker2 started (pid ${pid2})."

set +e
wait "$pid1"
status1=$?
wait "$pid2"
status2=$?
set -e

trap - EXIT INT TERM

echo ""
echo "=== OPML batch done. Converting to XMind ==="
./run_opml_to_xmind.sh

if [[ "$status1" -ne 0 || "$status2" -ne 0 ]]; then
  echo "worker1 exit: $status1"
  echo "worker2 exit: $status2"
  exit 1
fi

echo "Both workers finished. XMind files: outputs/xmind/"