#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec /usr/bin/python3 "$PROJECT_DIR/check_batteries.py"
