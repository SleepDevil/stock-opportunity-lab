#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
output_dir="${repo_root}/output"

rm -rf "${output_dir}"
mkdir -p "${output_dir}/backend" "${output_dir}/frontend"

npm --prefix "${repo_root}/frontend" ci
npm --prefix "${repo_root}/frontend" run build

cp -R "${repo_root}/backend/app" "${output_dir}/backend/app"
cp "${repo_root}/backend/pyproject.toml" "${output_dir}/backend/pyproject.toml"
cp -R "${repo_root}/frontend/dist" "${output_dir}/frontend/dist"
cp "${repo_root}/requirements.txt" "${output_dir}/requirements.txt"
cp "${repo_root}/server.py" "${output_dir}/server.py"
cp "${script_dir}/start.sh" "${output_dir}/start.sh"

chmod +x "${output_dir}/start.sh"
