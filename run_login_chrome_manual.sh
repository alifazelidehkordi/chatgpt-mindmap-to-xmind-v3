#!/usr/bin/env bash
# Open real Google Chrome for manual login (no Selenium). Most reliable for Google sign-in.
set -euo pipefail
cd "$(dirname "$0")"

LOGIN_PROFILE="${CHATGPT_LOGIN_PROFILE_DIR:-$PWD/chrome_profile_login}"

CHROME="${CHATGPT_CHROME_BINARY:-}"
if [[ -z "$CHROME" ]]; then
  for c in chromium-browser chromium google-chrome-stable google-chrome; do
    if command -v "$c" >/dev/null 2>&1; then
      CHROME="$(command -v "$c")"
      break
    fi
  done
fi

if [[ ! -x "$CHROME" ]]; then
  echo "Chrome not found. Install with: sudo dnf install chromium"
  echo "Or download Google Chrome, then set CHATGPT_CHROME_BINARY=/path/to/google-chrome"
  exit 1
fi

mkdir -p "$LOGIN_PROFILE"

echo "=== Manual ChatGPT Login (Real Chrome) ==="
echo "Chrome : $CHROME"
echo "Profile: $LOGIN_PROFILE"
echo ""
echo "1) Chrome will open ChatGPT"
echo "2) Click Log in and sign in with Google (this browser is accepted by Google)"
echo "3) When you see the chat box, CLOSE Chrome"
echo "4) Then run: ./run_login_chrome_manual.sh --copy"
echo ""

if [[ "${1:-}" == "--copy" ]]; then
  .venv-linux/bin/python - <<'PY'
from scripts.selenium_browser import copy_login_session, LOGIN_PROFILE_DIR, CHROME_PROFILE_DIR
copy_login_session(LOGIN_PROFILE_DIR, CHROME_PROFILE_DIR)
print("Done. Run: INPUT_DIR=/home/ali/Desktop/medlab ./run_pdf_to_xmind.sh --save-diagnostics")
PY
  exit 0
fi

# Never use chrome_profile/ here — Playwright's profile crashes real Chrome.
exec "$CHROME" \
  --user-data-dir="$LOGIN_PROFILE" \
  --profile-directory=Default \
  --no-first-run \
  --no-default-browser-check \
  --disable-blink-features=AutomationControlled \
  "https://chatgpt.com/?temporary-chat=true"