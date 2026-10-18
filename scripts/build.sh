#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
export GOTOOLCHAIN=local
export GOCACHE="$PWD/.cache/go-build"
export GOMODCACHE="$PWD/.cache/go-mod"
export GOMAXPROCS=4
command_name=${1:?command required}
output_path=${2:?output path required}
case "$command_name" in transitbench|csabench|gtfsimport|routebench|querygen|candidateprobe|tbbench|profilebench|mcbench|tadbench|legproof|corechbench|ultrabench|flashbench|tpbench|stpbench|trexbench|familybench|walkingparity|fixturecheck) ;; *) printf 'Unknown command\n' >&2; exit 1;; esac
build_hash=$(go run -mod=vendor ./cmd/sourcehash)
go build -mod=vendor -trimpath -ldflags "-X github.com/ertyoii/transit-routing-bench/experiment.BuildSourceSHA256=$build_hash" -o "$output_path" "./cmd/$command_name"
