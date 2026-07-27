#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

python_bin="${STOCK_LAB_DESKTOP_PYTHON:-}"
if [ -z "$python_bin" ]; then
  if [ -x ".venv/bin/python" ]; then
    python_bin=".venv/bin/python"
  elif [ -x ".venv/Scripts/python.exe" ]; then
    python_bin=".venv/Scripts/python.exe"
  fi
fi

if [ -z "$python_bin" ] || ! "$python_bin" -c "import sys" >/dev/null 2>&1; then
  echo "Desktop sidecar requires Python 3.12 with backend[desktop] installed. Run: npm run setup" >&2
  exit 1
fi

if ! command -v rustc >/dev/null 2>&1; then
  echo "Rust is required for a Tauri desktop build. Install Rust, then retry." >&2
  exit 1
fi

if ! "$python_bin" -c "import PyInstaller" >/dev/null 2>&1; then
  echo "PyInstaller is missing. Run: npm run setup" >&2
  exit 1
fi

target_triple="$(rustc --print host-tuple)"
binary_name="stock-lab-api"
case "$target_triple" in
  *-windows-*) binary_name="${binary_name}.exe" ;;
esac

build_root="$project_root/.desktop-build/pyinstaller"
binary_dir="$project_root/src-tauri/binaries"
mkdir -p "$binary_dir"
rm -rf "$build_root"

"$python_bin" -m PyInstaller \
  --noconfirm \
  --clean \
  --onefile \
  --name stock-lab-api \
  --paths backend \
  --distpath "$build_root/dist" \
  --workpath "$build_root/work" \
  --specpath "$build_root" \
  --collect-all akshare \
  --collect-all vectorbt \
  --collect-all curl_cffi \
  --collect-submodules uvicorn \
  desktop/sidecar.py

source_binary="$build_root/dist/$binary_name"
target_binary="$binary_dir/stock-lab-api-$target_triple"
if [[ "$binary_name" == *.exe ]]; then
  target_binary="${target_binary}.exe"
fi

cp "$source_binary" "$target_binary"
chmod 755 "$target_binary"
echo "Desktop API sidecar created: $target_binary"
