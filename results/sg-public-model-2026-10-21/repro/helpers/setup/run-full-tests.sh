#!/bin/bash
: "${SG_ROOT:?Set SG_ROOT to the portable research root}"
set -euo pipefail
source "${SG_ROOT}"/setup/environment.sh
setup="${SG_ROOT}"/setup
exec > >(tee "$setup/full-tests.log") 2>&1
set -x
date -u --iso-8601=seconds
cd "${SG_ROOT}"/routing
timeout -k 5s 420s taskset -c 0-3 go test -p=4 -count=1 -timeout=360s ./...
cd "${SG_ROOT}"/bench
timeout -k 5s 420s taskset -c 0-3 go test -mod=vendor -p=4 -count=1 -timeout=360s ./...
date -u --iso-8601=seconds
