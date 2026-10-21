#!/bin/bash
: "${SG_ROOT:?Set SG_ROOT to the portable research root}"
set -euo pipefail
source "${SG_ROOT}"/setup/environment.sh
exec taskset -c 0-3 "$@"
