#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./common.sh
source "$script_dir/common.sh"

usage() {
  cat <<'EOF'
Usage: scripts/dsx-connect-ng/deploy-k3s.sh --tag TAG [--registry REGISTRY] [--release NAME] [--namespace NS] [--values FILE] [--wait|--no-wait]

Deploys DSX-Connect v2 to the current Kubernetes context using Helm.

Examples:
  scripts/dsx-connect-ng/deploy-k3s.sh --tag dev --release dsx-connect --namespace dsx-connect
  scripts/dsx-connect-ng/deploy-k3s.sh --tag 2.0.0 --values dsx_connect_ng/deploy/helm/values-local.yaml --no-wait
EOF
}

require_value() {
  local option="$1"
  local value="${2:-}"
  if [[ -z "$value" || "$value" == --* ]]; then
    echo "$option requires a value" >&2
    exit 2
  fi
}

tag=""
registry="${DSX_CONNECT_NG_IMAGE_REGISTRY:-dsxconnect}"
release="dsx-connect"
namespace="dsx-connect"
values_file=""
wait="true"
timeout="3m"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag)
      require_value "$1" "${2:-}"
      tag="${2:-}"
      shift 2
      ;;
    --registry)
      require_value "$1" "${2:-}"
      registry="${2:-}"
      shift 2
      ;;
    --release)
      require_value "$1" "${2:-}"
      release="${2:-}"
      shift 2
      ;;
    --namespace|-n)
      require_value "$1" "${2:-}"
      namespace="${2:-}"
      shift 2
      ;;
    --values|-f)
      require_value "$1" "${2:-}"
      values_file="${2:-}"
      shift 2
      ;;
    --timeout)
      require_value "$1" "${2:-}"
      timeout="${2:-}"
      shift 2
      ;;
    --wait)
      wait="true"
      shift
      ;;
    --no-wait)
      wait="false"
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

if [[ -z "$tag" ]]; then
  echo "--tag is required" >&2
  exit 2
fi

if [[ -n "$values_file" && ! -f "$values_file" ]]; then
  echo "values file not found: $values_file" >&2
  exit 2
fi

chart_dir="$(ng_chart_dir)"
image_name="$(ng_image_name)"

helm_args=(
  upgrade --install "$release" "$chart_dir"
  --namespace "$namespace"
  --create-namespace
  --set "image.repository=$registry/$image_name"
  --set "image.tag=$tag"
)

if [[ -n "$values_file" ]]; then
  helm_args+=(-f "$values_file")
fi

if [[ "$wait" == "true" ]]; then
  helm_args+=(--wait --timeout "$timeout")
fi

echo "Deploying $registry/$image_name:$tag as release $release in namespace $namespace"
helm "${helm_args[@]}"

if [[ "$wait" == "true" ]]; then
  chart_name="dsx-connect"
  if [[ "$release" == *"$chart_name"* ]]; then
    api_deployment="$release-api"
  else
    api_deployment="$release-$chart_name-api"
  fi
  kubectl rollout status deployment "$api_deployment" \
    --namespace "$namespace" \
    --timeout "$timeout"
fi
