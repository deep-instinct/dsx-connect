#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./common.sh
source "$script_dir/common.sh"

usage() {
  cat <<'EOF'
Usage: scripts/connectors/build-image.sh CONNECTOR [--tag TAG]... [--registry REGISTRY] [--load|--push] [--platform PLATFORMS]

Examples:
  scripts/connectors/build-image.sh google_cloud_storage --tag dev --load
  scripts/connectors/build-image.sh google_cloud_storage --tag 0.5.55 --registry ghcr.io/org/dsx-connect --push
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

tags=()
registry="${CONNECTOR_IMAGE_REGISTRY:-dsxconnect}"
output_mode="load"
platform="${CONNECTOR_IMAGE_PLATFORM:-linux/amd64}"

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

root="$(repo_root)"
dir="$(connector_dir "$connector")"
version="$(connector_version "$connector")"
image_name="$(connector_image_name "$connector")"
if [[ ${#tags[@]} -eq 0 ]]; then
  tags=("$version")
fi
image_refs=()
for tag in "${tags[@]}"; do
  image_refs+=("$registry/$image_name:$tag")
done

if [[ "$output_mode" == "load" && "$platform" == *","* ]]; then
  echo "--load supports a single platform; got: $platform" >&2
  exit 2
fi

args=(
  docker buildx build
  --platform "$platform"
  -f "$dir/Dockerfile"
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

echo "Building ${image_refs[*]} from $dir/Dockerfile ($output_mode, $platform)"
"${args[@]}"
