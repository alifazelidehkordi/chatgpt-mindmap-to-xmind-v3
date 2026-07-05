#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

VENV_DIR=".venv-linux"
PYTHON="${VENV_DIR}/bin/python"

if [[ ! -x "${PYTHON}" ]]; then
  ./setup.sh
fi

OPML_DIR="${OPML_DIR:-outputs/opml}"
XMIND_DIR="${XMIND_DIR:-outputs/xmind}"

echo "=== OPML -> XMind only ==="
echo "OPML dir : ${OPML_DIR}"
echo "XMind dir: ${XMIND_DIR}"

"${PYTHON}" scripts/convert_opml_batch.py \
  --opml-dir "${OPML_DIR}" \
  --xmind-dir "${XMIND_DIR}" \
  "$@"