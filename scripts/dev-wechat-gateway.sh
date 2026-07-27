#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GATEWAY_DIR="$ROOT_DIR/.local-gateways/wechat-download-api"
BASE_URL="${STOCK_LAB_WECHAT_GATEWAY_BASE_URL:-}"

if [ -z "$BASE_URL" ] && [ -f "$ROOT_DIR/.env" ]; then
  BASE_URL="$(
    grep -E '^STOCK_LAB_WECHAT_GATEWAY_BASE_URL=' "$ROOT_DIR/.env" 2>/dev/null \
      | tail -n 1 \
      | cut -d= -f2- \
      | tr -d "\"'"
    true
  )"
fi

BASE_URL="${BASE_URL:-http://127.0.0.1:5500}"
HEALTH_URL="${BASE_URL%/}/api/health"
PYTHON_BIN="$GATEWAY_DIR/venv/bin/python"

if [ ! -d "$GATEWAY_DIR" ]; then
  echo "[wechat] Missing local gateway: $GATEWAY_DIR" >&2
  echo "[wechat] Run the gateway setup first, or clear STOCK_LAB_WECHAT_GATEWAY_BASE_URL to use manual feed mode." >&2
  exit 1
fi

if curl -fsS --max-time 1 "$HEALTH_URL" >/dev/null 2>&1; then
  echo "[wechat] Gateway already running at $BASE_URL"
  while true; do
    sleep 3600
  done
fi

if [ ! -f "$GATEWAY_DIR/.env" ]; then
  cp "$GATEWAY_DIR/env.example" "$GATEWAY_DIR/.env"
  {
    echo ""
    echo "SITE_URL=http://localhost:5500"
    echo "PORT=5500"
    echo "HOST=0.0.0.0"
  } >> "$GATEWAY_DIR/.env"
fi

if [ ! -x "$PYTHON_BIN" ]; then
  echo "[wechat] Creating gateway virtualenv..."
  python3 -m venv "$GATEWAY_DIR/venv"
  "$PYTHON_BIN" -m pip install --upgrade pip
  "$PYTHON_BIN" -m pip install -r "$GATEWAY_DIR/requirements.txt"
fi

echo "[wechat] Starting gateway at $BASE_URL"
cd "$GATEWAY_DIR"
exec "$PYTHON_BIN" app.py
