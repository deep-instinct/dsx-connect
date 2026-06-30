#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./common.sh
source "$script_dir/common.sh"

usage() {
  cat <<'EOF'
Usage: scripts/connectors/package-chart.sh CONNECTOR [--version VERSION] [--app-version VERSION] [--destination DIR] [--push OCI_REPO]

Examples:
  scripts/connectors/package-chart.sh google_cloud_storage
  scripts/connectors/package-chart.sh google_cloud_storage --push oci://registry-1.docker.io/dsxconnect
EOF
}

if [[ $# -eq 1 && ( "$1" == "-h" || "$1" == "--help" ) ]]; then
  usage
  exit 0
fi

if [[ $# -lt 1 ]]; then
  usage >&2
  exit 2
fi

connector="$1"
shift

version=""
app_version=""
destination="dist/charts"
push_repo=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)
      version="${2:-}"
      shift 2
      ;;
    --app-version)
      app_version="${2:-}"
      shift 2
      ;;
    --destination)
      destination="${2:-}"
      shift 2
      ;;
    --push)
      push_repo="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

root="$(repo_root)"
chart_dir="$(connector_chart_dir "$connector")"
version="${version:-$(connector_version "$connector")}"
app_version="${app_version:-$version}"
destination_path="$destination"
if [[ "$destination_path" != /* ]]; then
  destination_path="$root/$destination_path"
fi

mkdir -p "$destination_path"
helm lint "$chart_dir"
helm package "$chart_dir" \
  --version "$version" \
  --app-version "$app_version" \
  --destination "$destination_path"

if [[ -n "$push_repo" ]]; then
  chart_name="$(python3 - "$chart_dir/Chart.yaml" <<'PY'
import pathlib
import re
import sys

text = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
match = re.search(r"^name:\s*([^\s]+)", text, flags=re.MULTILINE)
if not match:
    raise SystemExit("Chart.yaml name not found")
print(match.group(1))
PY
)"
  helm push "$destination_path/$chart_name-$version.tgz" "$push_repo"
fi
