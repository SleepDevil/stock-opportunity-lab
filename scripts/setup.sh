#!/usr/bin/env bash
set -euo pipefail

if ! command -v python3.12 >/dev/null 2>&1; then
  echo "Python 3.12 is required for vectorbt. Install python3.12, then rerun: npm run setup" >&2
  exit 1
fi

if [ -x ".venv/bin/python" ]; then
  if ! ./.venv/bin/python - <<'PY'
import sys
raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)
PY
  then
    current_version="$(./.venv/bin/python --version 2>&1 || true)"
    echo "Existing .venv is not Python 3.12 (${current_version})." >&2
    echo "Rebuild it with: rm -rf .venv && npm run setup" >&2
    exit 1
  fi
fi

python3.12 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -e "backend[test,desktop]"
npm install
npm --prefix frontend install
