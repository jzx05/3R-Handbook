#!/usr/bin/env bash
# Local one-shot sync + audit.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python3 scripts/sync_upstream.py "$@"
python3 scripts/audit.py --strict
