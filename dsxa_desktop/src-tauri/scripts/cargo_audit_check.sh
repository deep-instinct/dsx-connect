#!/usr/bin/env bash
set -euo pipefail

# Temporary RustSec ignores for transitive advisories in Tauri/gtk/urlpattern stacks.
# Keep this list short-lived and prune as upstream fixes land.
IGNORES=(
  RUSTSEC-2024-0411
  RUSTSEC-2024-0412
  RUSTSEC-2024-0413
  RUSTSEC-2024-0414
  RUSTSEC-2024-0415
  RUSTSEC-2024-0416
  RUSTSEC-2024-0417
  RUSTSEC-2024-0418
  RUSTSEC-2024-0419
  RUSTSEC-2024-0420
  RUSTSEC-2024-0429
  RUSTSEC-2024-0370
  RUSTSEC-2025-0057
  RUSTSEC-2025-0075
  RUSTSEC-2025-0080
  RUSTSEC-2025-0081
  RUSTSEC-2025-0098
  RUSTSEC-2025-0100
)

ARGS=()
for id in "${IGNORES[@]}"; do
  ARGS+=(--ignore "$id")
done

cargo audit --deny warnings "${ARGS[@]}"
