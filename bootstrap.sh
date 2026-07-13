#!/usr/bin/env bash
# Dev environment bootstrap (macOS primary). Idempotent.
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements-dev.txt
# outlook-mcp is an installable package once Task 9 lands; skip before that.
if [ -f mcp/outlook-mcp/pyproject.toml ]; then
  pip install --quiet -e mcp/outlook-mcp
fi
pytest -q
echo "bootstrap OK"
