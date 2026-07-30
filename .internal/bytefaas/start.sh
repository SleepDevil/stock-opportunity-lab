#!/usr/bin/env bash

set -euo pipefail

export PYTHONUNBUFFERED="${PYTHONUNBUFFERED:-1}"
export STOCK_LAB_DATA_DIR="${STOCK_LAB_DATA_DIR:-/tmp/stock-opportunity-lab}"

mkdir -p "${STOCK_LAB_DATA_DIR}"

app_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="${app_root}/site-packages${PYTHONPATH:+:${PYTHONPATH}}"
port="${_FAAS_RUNTIME_PORT:-${TCE_PRIMARY_PORT:-${PORT:-8000}}}"

exec python3 -m uvicorn app.main:app \
  --app-dir "${app_root}/backend" \
  --host :: \
  --port "${port}" \
  --loop asyncio
