#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./common.sh
source "$script_dir/common.sh"

usage() {
  cat <<'EOF'
Usage: scripts/dsx-connect-ng/release.sh [--version VERSION] [--registry REGISTRY] [--helm-repo OCI_REPO] [--platform PLATFORMS] [--latest|--no-latest]

Builds and pushes the DSX-Connect v2 image, then packages and pushes its Helm chart.
Registry login must be done before running this script.

Examples:
  scripts/dsx-connect-ng/release.sh --registry dsxconnect --helm-repo oci://registry-1.docker.io/dsxconnect
  scripts/dsx-connect-ng/release.sh --version 2.0.0 --no-latest
EOF
}

version=""
registry="${DSX_CONNECT_NG_IMAGE_REGISTRY:-dsxconnect}"
helm_repo="${DSX_CONNECT_NG_HELM_REPO:-oci://registry-1.docker.io/dsxconnect}"
platform="${DSX_CONNECT_NG_IMAGE_PLATFORM:-linux/amd64,linux/arm64}"
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

version="${version:-$(ng_version)}"

python3 -m pytest dsx_connect_ng/tests
helm lint "$(ng_chart_dir)"
helm template dsx-connect "$(ng_chart_dir)" >/dev/null

build_args=(
  --tag "$version"
  --registry "$registry"
  --platform "$platform"
  --push
)
if [[ "$push_latest" == "true" ]]; then
  build_args+=(--tag latest)
fi

"$script_dir/build-image.sh" "${build_args[@]}"
"$script_dir/package-chart.sh" \
  --version "$version" \
  --app-version "$version" \
  --push "$helm_repo"
