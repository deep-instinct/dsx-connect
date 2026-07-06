#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./common.sh
source "$script_dir/common.sh"

usage() {
  cat <<'EOF'
Usage: scripts/dsx-connect-ng/build-image.sh [--tag TAG]... [--registry REGISTRY] [--load|--push] [--platform PLATFORMS]

Examples:
  scripts/dsx-connect-ng/build-image.sh --tag dev --load
  scripts/dsx-connect-ng/build-image.sh --tag 2.0.0 --registry dsxconnect --push --platform linux/amd64,linux/arm64
EOF
}

tags=()
registry="${DSX_CONNECT_NG_IMAGE_REGISTRY:-dsxconnect}"
output_mode="load"
platform="${DSX_CONNECT_NG_IMAGE_PLATFORM:-linux/amd64}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag)
      tags+=("${2:-}")
      shift 2
      ;;
    --registry)
      registry="${2:-}"
      shift 2
      ;;
    --load)
      output_mode="load"
      shift
      ;;
    --push)
      output_mode="push"
      shift
      ;;
    --platform|--platforms)
      platform="${2:-}"
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

if [[ ${#tags[@]} -eq 0 ]]; then
  tags=("$(ng_version)")
fi

if [[ "$output_mode" == "load" && "$platform" == *","* ]]; then
  echo "--load supports a single platform; got: $platform" >&2
  exit 2
fi

root="$(repo_root)"
image_name="$(ng_image_name)"
image_refs=()
for tag in "${tags[@]}"; do
  image_refs+=("$registry/$image_name:$tag")
done

args=(
  docker buildx build
  --platform "$platform"
  -f "$root/dsx_connect_ng/Dockerfile"
)

for image_ref in "${image_refs[@]}"; do
  args+=(-t "$image_ref")
done

if [[ "$output_mode" == "push" ]]; then
  args+=(--push)
else
  args+=(--load)
fi

args+=("$root")

echo "Building ${image_refs[*]} from dsx_connect_ng/Dockerfile ($output_mode, $platform)"
"${args[@]}"
