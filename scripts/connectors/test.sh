#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./common.sh
source "$script_dir/common.sh"

if [[ $# -ne 1 ]]; then
  echo "Usage: scripts/connectors/test.sh CONNECTOR" >&2
  exit 2
fi

connector="$1"
root="$(repo_root)"
dir="$(connector_dir "$connector")"

if [[ ! -d "$dir/tests" ]]; then
  echo "No tests directory for connector: $connector"
  exit 0
fi

python_bin="${PYTHON:-$root/.venv/bin/python}"
if [[ ! -x "$python_bin" ]]; then
  python_bin="${PYTHON:-python3}"
fi

"$python_bin" -m pytest "$dir/tests"
