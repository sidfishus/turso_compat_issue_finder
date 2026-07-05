#!/usr/bin/env bash
# Find next compat discrepancy, repro, and search GitHub. Requires gh auth for search.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "$ROOT"

export TURSO_COMPAT_TURSODB="${TURSO_COMPAT_TURSODB:-/home/sid/dev/projects/turso/target/debug/tursodb}"
export TURSO_COMPAT_COMPAT_MD="${TURSO_COMPAT_COMPAT_MD:-/home/sid/dev/projects/turso/COMPAT.md}"

echo "=== Refreshing checklist ==="
.venv/bin/python -m inventory.checklist
echo ""

echo "=== Next candidate ==="
.venv/bin/python -m inventory.next_issue next --repro --search "$@"
