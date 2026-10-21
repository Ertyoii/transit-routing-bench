: "${SG_ROOT:?Set SG_ROOT to the portable research root}"
# Source this file before cloud-only Go builds/tests/evaluations.
export PATH="${SG_ROOT}"/setup/toolchain/go/bin:$PATH
export GOTOOLCHAIN=local
export GOMAXPROCS=4
export GOMEMLIMIT=7GiB
export GOPROXY=off
export GOSUMDB=off
export GOCACHE="${SG_ROOT}"/setup/cache/go-build
export GOMODCACHE="${SG_ROOT}"/setup/cache/go-mod
# taskset -c 0-3 is required separately for a four-logical-CPU affinity cap.
# GOMEMLIMIT is a Go soft GC target, NOT a hard total RSS/cgroup memory cap.
