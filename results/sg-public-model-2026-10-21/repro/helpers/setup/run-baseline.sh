#!/bin/bash
: "${SG_ROOT:?Set SG_ROOT to the portable research root}"
set -euo pipefail
source "${SG_ROOT}"/setup/environment.sh
setup="${SG_ROOT}"/setup
exec > >(tee "$setup/baseline.log") 2>&1
set -x
date -u --iso-8601=seconds
go version
go env GOOS GOARCH GOAMD64 GOTOOLCHAIN GOMAXPROCS GOMEMLIMIT GOPROXY GOSUMDB GOCACHE
cd "${SG_ROOT}"/routing
timeout 180s taskset -c 0-3 go test -p=4 -count=1 -timeout=120s ./raptor ./walking/graph ./walking/transit ./walking/osm ./walking/httpapi ./walking
cd "${SG_ROOT}"/bench
timeout 180s taskset -c 0-3 go test -mod=vendor -p=4 -count=1 -timeout=120s ./fixtures ./evaluation ./experiment
build_hash=$(timeout 120s taskset -c 0-3 go run -mod=vendor ./cmd/sourcehash)
printf '%s\n' "$build_hash" > "$setup/bench-build-source-sha256.txt"
timeout 180s taskset -c 0-3 go build -mod=vendor -p=4 -trimpath -ldflags "-X github.com/ertyoii/transit-routing-bench/experiment.BuildSourceSHA256=$build_hash" -o "$setup/familybench" ./cmd/familybench
sha256sum "$setup/familybench"
timeout 15s taskset -c 0-3 "$setup/familybench" -h > "$setup/familybench-help.txt" 2>&1
date -u --iso-8601=seconds
