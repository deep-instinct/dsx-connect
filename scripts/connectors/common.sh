#!/usr/bin/env bash
set -euo pipefail

repo_root() {
  git rev-parse --show-toplevel
}

connector_dir() {
  local connector="$1"
  local root
  root="$(repo_root)"
  local dir="$root/connectors/$connector"
  if [[ ! -d "$dir" ]]; then
    echo "connector directory not found: $dir" >&2
    return 1
  fi
  printf '%s\n' "$dir"
}

connector_image_name() {
  local connector="$1"
  printf '%s-connector\n' "${connector//_/-}"
}

connector_version() {
  local connector="$1"
  local dir
  dir="$(connector_dir "$connector")"
  python3 - "$dir/version.py" <<'PY'
import pathlib
import re
import sys

text = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
match = re.search(r"CONNECTOR_VERSION\s*=\s*['\"]([^'\"]+)['\"]", text)
if not match:
    raise SystemExit(f"CONNECTOR_VERSION not found in {sys.argv[1]}")
print(match.group(1))
PY
}

connector_chart_dir() {
  local connector="$1"
  local dir
  dir="$(connector_dir "$connector")/deploy/helm"
  if [[ ! -f "$dir/Chart.yaml" ]]; then
    echo "connector chart not found: $dir/Chart.yaml" >&2
    return 1
  fi
  printf '%s\n' "$dir"
}
