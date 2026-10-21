#!/bin/bash
: "${SG_ROOT:?Set SG_ROOT to the portable research root}"
# Existing public importer only. This is preparation, not a routing benchmark.
set -euo pipefail
BASE="${SG_ROOT}"
source "$BASE/setup/environment.sh"
cd "$BASE/bench"
SOURCE_HASH=$(cat "$BASE/setup/bench-build-source-sha256.txt")
RAW_HASH=d92173127e9a5cbf8ecb5b4d50ab03f68deb7f8ddff73648b8ffb33c70ab4801
printf '%s  %s\n' "$RAW_HASH" "$BASE/data/singapore-gtfs-v2026-07-12.zip" | sha256sum -c -
# Preserve offline source binding; source/cache remain the prepared baseline.
taskset -c 0-3 go build -mod=vendor -p=4 -trimpath \
  -ldflags "-X github.com/ertyoii/transit-routing-bench/experiment.BuildSourceSHA256=$SOURCE_HASH" \
  -o "$BASE/data/gtfsimport" ./cmd/gtfsimport
sha256sum "$BASE/data/gtfsimport" > "$BASE/data/gtfsimport.sha256"
while read -r NAME DATE START END; do
  OUT="$BASE/data/$NAME"
  mkdir "$OUT"
  printf '%s\n' "Import $NAME date=$DATE window=$START..$END" | tee "$OUT/import.log"
  set +e
  timeout 180s taskset -c 0-3 "$BASE/data/gtfsimport" \
    -zip "$BASE/data/singapore-gtfs-v2026-07-12.zip" -sha256 "$RAW_HASH" \
    -date "$DATE" -start "$START" -end "$END" \
    -frequency-policy deterministic_model -data-kind modeled_snapshot \
    -transfer-edges minimum_time_proxy -max-connections 1000000 \
    -out "$OUT/dataset.json" -report "$OUT/import-audit.json" >> "$OUT/import.log" 2>&1
  STATUS=$?
  set -e
  printf '%s\n' "$STATUS" > "$OUT/exit-code.txt"
  cat "$OUT/import.log"
  # Every requested window retains status even if unsupported/empty. Never trim.
done <<'WINDOWS'
weekday-morning-20261020 2026-10-20 25200 36000
weekday-midday-20261020 2026-10-20 43200 54000
weekday-evening-20261020 2026-10-20 61200 72000
weekday-overnight-20261020 2026-10-20 82800 93600
weekend-midday-20261024 2026-10-24 43200 54000
WINDOWS
