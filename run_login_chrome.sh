#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "=== ChatGPT Login (Real Chrome) ==="
echo "Google blocks login in Playwright Chromium."
echo "This opens real Google Chrome for one-time login."
echo ""
echo "If this fails, use the manual script instead:"
echo "  ./run_login_chrome_manual.sh"
echo "  (after login) ./run_login_chrome_manual.sh --copy"
echo ""

VENV_DIR=".venv-linux"
PYTHON="${VENV_DIR}/bin/python"

if [[ ! -x "${PYTHON}" ]]; then
  ./setup.sh
fi

if ! "${PYTHON}" -c "import selenium" 2>/dev/null; then
  "${PYTHON}" -m pip install --upgrade pip
  "${PYTHON}" -m pip install -r requirements.txt
fi

"${PYTHON}" scripts/run_login_chrome.py "$@"