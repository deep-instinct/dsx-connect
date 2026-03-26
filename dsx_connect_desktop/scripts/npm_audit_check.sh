#!/usr/bin/env bash
set -euo pipefail

# Keep aligned with CI policy: production dependencies only, fail on high+.
npm audit --omit=dev --audit-level=high
