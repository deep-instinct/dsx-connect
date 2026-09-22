#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: stage-macos-artifacts.sh <variant> <arch>" >&2
  exit 2
fi

VARIANT="$1"
ARCH="$2"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
DIST_DIR="${DESKTOP_DIR}/dist"
OUT_DIR="${DIST_DIR}/${VARIANT}"

mkdir -p "${OUT_DIR}"

found=0
for artifact in "${DIST_DIR}"/*.dmg "${DIST_DIR}"/*.zip; do
  [[ -e "${artifact}" ]] || continue
  found=1
  filename="$(basename "${artifact}")"
  extension="${filename##*.}"
  stem="${filename%.*}"
  mv "${artifact}" "${OUT_DIR}/${stem}-macos-${ARCH}-${VARIANT}.${extension}"
done

if [[ "${found}" -ne 1 ]]; then
  echo "No macOS .dmg or .zip artifacts found in ${DIST_DIR}" >&2
  exit 1
fi

rm -rf "${DIST_DIR}/mac" "${DIST_DIR}"/mac-*
