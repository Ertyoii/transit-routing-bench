#!/bin/bash
: "${SG_ROOT:?Set SG_ROOT to the portable research root}"
set -euo pipefail
base="${SG_ROOT}"
bench=$base/bench-auxiliary-public
out=$base/public-campaign-20261021/auxiliary-native
exec 9>"$base/setup/campaign.lock"
flock -n 9 || { echo "Blocked: an active campaign holds the shared timing lock; no build or test launched." >&2; exit 75; }
source "$base/setup/environment.sh"
cd "$bench"
validation_label=${1:-validation-v2}
case "$validation_label" in validation-v2|validation-v2-retry[0-9]*) ;; *) echo "Invalid validation label" >&2; exit 2;; esac
validation="$out/$validation_label"
mkdir "$validation"
go version | tee "$validation/go-version.txt"
git status --short > "$validation/git-status.txt"
git diff --binary f5fb8ebf5fbbb030ab0c3ed4c7feee33dff7311c > "$validation/complete-source.patch"
git diff --name-only f5fb8ebf5fbbb030ab0c3ed4c7feee33dff7311c > "$validation/changed-files.txt"
go test -timeout 180s -count=1 -mod=vendor ./cmd/corechgraphbench ./cmd/profilebench ./cmd/tadbench ./cmd/ultrabench ./regression/corech ./regression/profilequery ./regression/tad ./regression/ultra ./experiment 2>&1 | tee "$validation/focused-tests.log"
go vet -mod=vendor ./cmd/corechgraphbench ./cmd/profilebench ./cmd/tadbench ./cmd/ultrabench 2>&1 | tee "$validation/vet.log"
build_hash=$(go run -mod=vendor ./cmd/sourcehash)
printf '%s\n' "$build_hash" > "$validation/build-source-sha256.txt"
for command_name in corechgraphbench profilebench tadbench ultrabench; do
 go build -mod=vendor -trimpath -ldflags "-X github.com/ertyoii/transit-routing-bench/experiment.BuildSourceSHA256=$build_hash" -o "$out/$command_name" "./cmd/$command_name"
 sha256sum "$out/$command_name" >> "$validation/binaries-sha256.txt"
 go version -m "$out/$command_name" > "$validation/$command_name-build-info.txt"
done
# Build output is outside source roots. These help checks execute no workload.
for command_name in corechgraphbench profilebench tadbench ultrabench; do
 "$out/$command_name" -help > "$validation/$command_name-help.txt" 2>&1
done
printf 'Focused checks and four source-bound auxiliary builds passed. No public routing workload executed.\n'
