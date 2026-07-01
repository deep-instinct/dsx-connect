#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./common.sh
source "$script_dir/common.sh"

usage() {
  cat <<'EOF'
Usage: scripts/connectors/deploy-k3s.sh CONNECTOR --tag TAG [--registry REGISTRY] [--release NAME] [--namespace NS] [--values FILE] [--wait|--no-wait]

Deploys a connector chart to the current Kubernetes context using Helm.

Examples:
  scripts/connectors/deploy-k3s.sh google_cloud_storage --tag ci-abcd123 --release gcs --namespace dsx-connect
  scripts/connectors/deploy-k3s.sh google_cloud_storage --tag 0.5.55 --values values-demo.yaml --wait
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

require_value() {
  local option="$1"
  local value="${2:-}"
  if [[ -z "$value" || "$value" == --* ]]; then
    echo "$option requires a value" >&2
    exit 2
  fi
}

connector="$1"
shift

tag=""
registry="${CONNECTOR_IMAGE_REGISTRY:-dsxconnect}"
release=""
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

chart_dir="$(connector_chart_dir "$connector")"
image_name="$(connector_image_name "$connector")"
release="${release:-${image_name%-connector}}"

helm_args=(
  upgrade --install "$release" "$chart_dir"
  --namespace "$namespace"
  --create-namespace
  --set "image.repository=$registry/$image_name"
  --set "image.tag=$tag"
  --set "image.pullPolicy=Always"
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
  kubectl rollout status deployment \
    --namespace "$namespace" \
    --selector "app.kubernetes.io/instance=$release" \
    --timeout "$timeout"
fi
