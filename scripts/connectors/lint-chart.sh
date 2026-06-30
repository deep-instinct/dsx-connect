#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./common.sh
source "$script_dir/common.sh"

if [[ $# -ne 1 ]]; then
  echo "Usage: scripts/connectors/lint-chart.sh CONNECTOR" >&2
  exit 2
fi

connector="$1"
chart_dir="$(connector_chart_dir "$connector")"
release_name="connector-test-${connector//_/-}"

helm lint "$chart_dir"
helm template "$release_name" "$chart_dir" >/dev/null
