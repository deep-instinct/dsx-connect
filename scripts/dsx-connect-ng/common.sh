#!/usr/bin/env bash
set -euo pipefail

repo_root() {
  git rev-parse --show-toplevel
}

ng_version() {
  local root
  root="$(repo_root)"
  python3 - "$root/dsx_connect_ng/pyproject.toml" <<'PY'
import pathlib
import re
import sys

text = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
match = re.search(r"^version\s*=\s*['\"]([^'\"]+)['\"]", text, flags=re.MULTILINE)
if not match:
    raise SystemExit(f"version not found in {sys.argv[1]}")
print(match.group(1))
PY
}

ng_image_name() {
  printf '%s\n' "dsx-connect"
}

ng_chart_dir() {
  local root
  root="$(repo_root)"
  local dir="$root/dsx_connect_ng/deploy/helm"
  if [[ ! -f "$dir/Chart.yaml" ]]; then
    echo "NG chart not found: $dir/Chart.yaml" >&2
    return 1
  fi
  printf '%s\n' "$dir"
}
