#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../.." && pwd)"

# shellcheck source=./common.sh
source "$script_dir/common.sh"
# shellcheck source=../connectors/common.sh
source "$repo_root/scripts/connectors/common.sh"

usage() {
  cat <<'EOF'
Usage: scripts/dsx-connect-ng/update-lab-stack.sh [options]

Updates a lab Kubernetes/k3s stack from released OCI Helm charts.
The lab VM keeps its environment-specific values files locally; this script
only selects chart/image versions and runs helm upgrade --install.

Defaults:
  DSX-Connect chart version: current dsx_connect_ng/pyproject.toml
  GCS connector version:     current connectors/google_cloud_storage/version.py
  Filesystem version:        current connectors/filesystem/version.py
  OCI chart repo:            oci://registry-1.docker.io/dsxconnect
  OCI chart names:           dsx-connect-chart, google-cloud-storage-connector-chart, filesystem-connector-chart

Examples:
  scripts/dsx-connect-ng/update-lab-stack.sh \
    --core-values ~/.dsx-connect-lab/dsx-connect-values.yaml \
    --gcs-values ~/.dsx-connect-lab/gcs-values.yaml

  scripts/dsx-connect-ng/update-lab-stack.sh \
    --connect-version 2.0.3 \
    --gcs-version 2.0.3 \
    --filesystem-version 2.0.5 \
    --skip-filesystem

Options:
  --namespace, -n NAME             Kubernetes namespace (default: dsx-connect)
  --kube-context NAME             Optional kube context for helm
  --chart-repo OCI_REPO           OCI chart repo (default: oci://registry-1.docker.io/dsxconnect)
  --image-registry REGISTRY       Optional image registry override (example: dsxconnect)
  --pull-policy POLICY            Image pull policy override (default: IfNotPresent)
  --timeout DURATION              Helm wait timeout (default: 5m)
  --wait | --no-wait              Wait for rollouts (default: wait)
  --dry-run                       Render/validate without applying changes

  --connect-version VERSION       DSX-Connect chart/app version
  --connector-version VERSION     Version for all connectors unless overridden
  --gcs-version VERSION           GCS connector chart/app version
  --filesystem-version VERSION    Filesystem connector chart/app version

  --core-release NAME             DSX-Connect Helm release (default: dsx-connect)
  --gcs-release NAME              GCS Helm release (default: gcs)
  --filesystem-release NAME       Filesystem Helm release (default: fs)

  --core-values FILE              DSX-Connect values file
  --gcs-values FILE               GCS connector values file
  --filesystem-values FILE        Filesystem connector values file

  --skip-core                     Do not update DSX-Connect
  --skip-gcs                      Do not update GCS connector
  --skip-filesystem               Do not update filesystem connector
  -h, --help                      Show this help
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

expand_path() {
  local value="$1"
  if [[ "$value" == "~/"* ]]; then
    printf '%s/%s\n' "$HOME" "${value#"~/"}"
  else
    printf '%s\n' "$value"
  fi
}

validate_values_file() {
  local label="$1"
  local path="$2"
  if [[ -n "$path" && ! -f "$path" ]]; then
    echo "$label values file not found: $path" >&2
    exit 2
  fi
}

connect_version="${DSX_CONNECT_VERSION:-$(ng_version)}"
connector_default_version="${CONNECTOR_VERSION:-}"
gcs_version="${GCS_CONNECTOR_VERSION:-}"
filesystem_version="${FILESYSTEM_CONNECTOR_VERSION:-}"

namespace="${DSX_CONNECT_NAMESPACE:-dsx-connect}"
kube_context="${KUBE_CONTEXT:-}"
chart_repo="${DSX_CONNECT_CHART_REPO:-oci://registry-1.docker.io/dsxconnect}"
image_registry="${DSX_CONNECT_IMAGE_REGISTRY:-}"
pull_policy="${DSX_CONNECT_IMAGE_PULL_POLICY:-IfNotPresent}"
timeout="${DSX_CONNECT_UPDATE_TIMEOUT:-5m}"
wait="true"
dry_run="false"

core_release="${DSX_CONNECT_RELEASE:-dsx-connect}"
gcs_release="${GCS_CONNECTOR_RELEASE:-gcs}"
filesystem_release="${FILESYSTEM_CONNECTOR_RELEASE:-fs}"

core_values="${DSX_CONNECT_VALUES:-}"
gcs_values="${GCS_CONNECTOR_VALUES:-}"
filesystem_values="${FILESYSTEM_CONNECTOR_VALUES:-}"

skip_core="false"
skip_gcs="false"
skip_filesystem="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --namespace|-n)
      require_value "$1" "${2:-}"
      namespace="${2:-}"
      shift 2
      ;;
    --kube-context)
      require_value "$1" "${2:-}"
      kube_context="${2:-}"
      shift 2
      ;;
    --chart-repo)
      require_value "$1" "${2:-}"
      chart_repo="${2:-}"
      shift 2
      ;;
    --image-registry)
      require_value "$1" "${2:-}"
      image_registry="${2:-}"
      shift 2
      ;;
    --pull-policy)
      require_value "$1" "${2:-}"
      pull_policy="${2:-}"
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
    --dry-run)
      dry_run="true"
      shift
      ;;
    --connect-version)
      require_value "$1" "${2:-}"
      connect_version="${2:-}"
      shift 2
      ;;
    --connector-version)
      require_value "$1" "${2:-}"
      connector_default_version="${2:-}"
      shift 2
      ;;
    --gcs-version)
      require_value "$1" "${2:-}"
      gcs_version="${2:-}"
      shift 2
      ;;
    --filesystem-version)
      require_value "$1" "${2:-}"
      filesystem_version="${2:-}"
      shift 2
      ;;
    --core-release)
      require_value "$1" "${2:-}"
      core_release="${2:-}"
      shift 2
      ;;
    --gcs-release)
      require_value "$1" "${2:-}"
      gcs_release="${2:-}"
      shift 2
      ;;
    --filesystem-release)
      require_value "$1" "${2:-}"
      filesystem_release="${2:-}"
      shift 2
      ;;
    --core-values)
      require_value "$1" "${2:-}"
      core_values="$(expand_path "${2:-}")"
      shift 2
      ;;
    --gcs-values)
      require_value "$1" "${2:-}"
      gcs_values="$(expand_path "${2:-}")"
      shift 2
      ;;
    --filesystem-values)
      require_value "$1" "${2:-}"
      filesystem_values="$(expand_path "${2:-}")"
      shift 2
      ;;
    --skip-core)
      skip_core="true"
      shift
      ;;
    --skip-gcs)
      skip_gcs="true"
      shift
      ;;
    --skip-filesystem)
      skip_filesystem="true"
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

if [[ -n "$connector_default_version" ]]; then
  gcs_version="${gcs_version:-$connector_default_version}"
  filesystem_version="${filesystem_version:-$connector_default_version}"
fi
gcs_version="${gcs_version:-$(connector_version google_cloud_storage)}"
filesystem_version="${filesystem_version:-$(connector_version filesystem)}"

core_values="$(expand_path "$core_values")"
gcs_values="$(expand_path "$gcs_values")"
filesystem_values="$(expand_path "$filesystem_values")"

validate_values_file "DSX-Connect" "$core_values"
validate_values_file "GCS connector" "$gcs_values"
validate_values_file "Filesystem connector" "$filesystem_values"

helm_base_args=(--namespace "$namespace" --create-namespace)
if [[ -n "$kube_context" ]]; then
  helm_base_args+=(--kube-context "$kube_context")
fi
if [[ "$wait" == "true" && "$dry_run" == "false" ]]; then
  helm_base_args+=(--wait --timeout "$timeout")
fi
if [[ "$dry_run" == "true" ]]; then
  helm_base_args+=(--dry-run)
fi

helm_upgrade() {
  local release="$1"
  local chart="$2"
  local version="$3"
  local values_file="$4"
  shift 4

  local args=(upgrade --install "$release" "$chart" --version "$version" "${helm_base_args[@]}")
  if [[ -n "$values_file" ]]; then
    args+=(-f "$values_file")
  fi
  args+=("$@")

  printf '\n==> helm %s\n' "${args[*]}"
  helm "${args[@]}"
}

if [[ "$skip_core" != "true" ]]; then
  core_set_args=()
  if [[ -n "$image_registry" ]]; then
    core_set_args+=(--set "image.repository=$image_registry/dsx-connect")
  fi
  core_set_args+=(--set "image.pullPolicy=$pull_policy")
  helm_upgrade \
    "$core_release" \
    "$chart_repo/dsx-connect-chart" \
    "$connect_version" \
    "$core_values" \
    "${core_set_args[@]}"
fi

if [[ "$skip_gcs" != "true" ]]; then
  gcs_set_args=()
  if [[ -n "$image_registry" ]]; then
    gcs_set_args+=(--set "image.repository=$image_registry/google-cloud-storage-connector")
  fi
  gcs_set_args+=(--set "image.pullPolicy=$pull_policy")
  helm_upgrade \
    "$gcs_release" \
    "$chart_repo/google-cloud-storage-connector-chart" \
    "$gcs_version" \
    "$gcs_values" \
    "${gcs_set_args[@]}"
fi

if [[ "$skip_filesystem" != "true" ]]; then
  filesystem_set_args=()
  if [[ -n "$image_registry" ]]; then
    filesystem_set_args+=(--set "image.repository=$image_registry/filesystem-connector")
  fi
  filesystem_set_args+=(--set "image.pullPolicy=$pull_policy")
  helm_upgrade \
    "$filesystem_release" \
    "$chart_repo/filesystem-connector-chart" \
    "$filesystem_version" \
    "$filesystem_values" \
    "${filesystem_set_args[@]}"
fi

if [[ "$dry_run" == "false" ]]; then
  printf '\nUpdated DSX-Connect lab stack in namespace %s\n' "$namespace"
  helm list --namespace "$namespace"
fi
