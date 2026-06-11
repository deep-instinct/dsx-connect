#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${DESKTOP_DIR}/.." && pwd)"
OUT_DIR="${DESKTOP_DIR}/bundled-python"
PYTHON_VERSION="${DSXCONNECT_DESKTOP_PYTHON_VERSION:-3.12}"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required to prepare the bundled Python runtime" >&2
  exit 1
fi

rm -rf "${OUT_DIR}"
mkdir -p "${OUT_DIR}"

uv python install "${PYTHON_VERSION}"
PYTHON_BIN="$(uv python find "${PYTHON_VERSION}")"
PYTHON_ROOT="$(cd "$(dirname "${PYTHON_BIN}")/.." && pwd)"

if command -v ditto >/dev/null 2>&1; then
  ditto "${PYTHON_ROOT}" "${OUT_DIR}"
else
  cp -R "${PYTHON_ROOT}/." "${OUT_DIR}/"
fi

BUNDLED_PYTHON="${OUT_DIR}/bin/python3"
if [[ ! -x "${BUNDLED_PYTHON}" ]]; then
  BUNDLED_PYTHON="${OUT_DIR}/bin/python"
fi
if [[ ! -x "${BUNDLED_PYTHON}" ]]; then
  echo "Bundled Python executable not found under ${OUT_DIR}/bin" >&2
  exit 1
fi

"${BUNDLED_PYTHON}" -m ensurepip --upgrade || true
"${BUNDLED_PYTHON}" -m pip install --upgrade pip setuptools wheel
"${BUNDLED_PYTHON}" -m pip install -r "${REPO_ROOT}/dsx_connect/requirements.txt"

for req in "${REPO_ROOT}"/connectors/*/requirements.txt; do
  "${BUNDLED_PYTHON}" -m pip install -r "${req}"
done

"${BUNDLED_PYTHON}" -m pip install \
  "${REPO_ROOT}/shared" \
  "${REPO_ROOT}/dsxa_sdk_py" \
  "${REPO_ROOT}/dsx_connect_sdk"

"${BUNDLED_PYTHON}" - <<'PY'
import aiohttp
import celery
import fastapi
import httpx
import pydantic
import redis
import typer
import uvicorn

import dsx_connect_sdk
import dsxa_sdk_py
import shared

print("Bundled Python runtime import validation passed")
PY

echo "Prepared bundled Python runtime at ${OUT_DIR}"
