#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
OUT_DIR="${DESKTOP_DIR}/bundled-redis"
BIN_DIR="${OUT_DIR}/bin"
LIB_DIR="${OUT_DIR}/lib"

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required to prepare the bundled Redis runtime on macOS" >&2
  exit 1
fi

if ! brew --prefix redis >/dev/null 2>&1; then
  brew install redis
fi

REDIS_PREFIX="${DSXCONNECT_DESKTOP_REDIS_PREFIX:-$(brew --prefix redis)}"
REDIS_SERVER="${REDIS_PREFIX}/bin/redis-server"

if [[ ! -x "${REDIS_SERVER}" ]]; then
  echo "redis-server not found at ${REDIS_SERVER}" >&2
  exit 1
fi

rm -rf "${OUT_DIR}"
mkdir -p "${BIN_DIR}" "${LIB_DIR}"
cp "${REDIS_SERVER}" "${BIN_DIR}/redis-server"
chmod u+w "${BIN_DIR}/redis-server"
chmod +x "${BIN_DIR}/redis-server"

copy_dependency_tree() {
  local target="$1"
  local dep dep_name copied

  while IFS= read -r dep; do
    [[ -z "${dep}" ]] && continue
    [[ "${dep}" == @* ]] && continue
    [[ "${dep}" == /usr/lib/* ]] && continue
    [[ "${dep}" == /System/* ]] && continue
    [[ ! -f "${dep}" ]] && continue

    dep_name="$(basename "${dep}")"
    copied="${LIB_DIR}/${dep_name}"

    if [[ ! -f "${copied}" ]]; then
      cp "${dep}" "${copied}"
      chmod u+w "${copied}"
      copy_dependency_tree "${copied}"
      install_name_tool -id "@executable_path/../lib/${dep_name}" "${copied}" || true
    fi

    install_name_tool -change "${dep}" "@executable_path/../lib/${dep_name}" "${target}" || true
  done < <(otool -L "${target}" | awk 'NR > 1 { print $1 }')
}

copy_dependency_tree "${BIN_DIR}/redis-server"
install_name_tool -add_rpath "@executable_path/../lib" "${BIN_DIR}/redis-server" 2>/dev/null || true

"${BIN_DIR}/redis-server" --version

echo "Prepared bundled Redis runtime at ${OUT_DIR}"
