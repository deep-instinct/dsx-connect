#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./common.sh
source "$script_dir/common.sh"

usage() {
  cat <<'EOF'
Usage: scripts/connectors/release.sh CONNECTOR [--version VERSION] [--registry REGISTRY] [--helm-repo OCI_REPO] [--platform PLATFORMS] [--latest|--no-latest]

Builds and pushes a connector image, then packages and pushes its Helm chart.
Registry login must be done before running this script.

Examples:
  scripts/connectors/release.sh google_cloud_storage --registry dsxconnect --helm-repo oci://registry-1.docker.io/dsxconnect
  scripts/connectors/release.sh google_cloud_storage --version 0.5.55 --no-latest
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
registry="${CONNECTOR_IMAGE_REGISTRY:-dsxconnect}"
helm_repo="${CONNECTOR_HELM_REPO:-oci://registry-1.docker.io/dsxconnect}"
platform="${CONNECTOR_IMAGE_PLATFORM:-linux/amd64,linux/arm64}"
push_latest="true"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)
      version="${2:-}"
      shift 2
      ;;
    --registry)
      registry="${2:-}"
      shift 2
      ;;
    --helm-repo)
      helm_repo="${2:-}"
      shift 2
      ;;
    --platform|--platforms)
      platform="${2:-}"
      shift 2
      ;;
    --latest)
      push_latest="true"
      shift
      ;;
    --no-latest)
      push_latest="false"
      shift
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

version="${version:-$(connector_version "$connector")}"

"$script_dir/test.sh" "$connector"
"$script_dir/lint-chart.sh" "$connector"

build_args=(
  "$connector"
  --tag "$version"
  --registry "$registry"
  --platform "$platform"
  --push
)
if [[ "$push_latest" == "true" ]]; then
  build_args+=(--tag latest)
fi

"$script_dir/build-image.sh" "${build_args[@]}"
"$script_dir/package-chart.sh" "$connector" \
  --version "$version" \
  --app-version "$version" \
  --push "$helm_repo"
