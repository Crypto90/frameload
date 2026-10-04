#!/usr/bin/env bash
# Quick runner for FrameLoad on Steam Frame / Linux
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="${SCRIPT_DIR}:${PYTHONPATH:-}"

python3 -m frameload.cli serve "$@"
