#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
exec python3 scripts/reproduce-checkpoint.py "${1:?new output directory required}"
