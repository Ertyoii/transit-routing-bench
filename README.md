# Transit routing benchmark harness

Independent finite-instance oracles, regression checks and reproducible measurement tools for [transit-routing-go](https://github.com/ertyoii/transit-routing-go). Original code and documentation are [MIT licensed](LICENSE). Only original synthetic data is included, under its separate CC0 notice. See [data and third-party boundaries](THIRD_PARTY_NOTICES.md).

Requires Go 1.27.x. The routing dependency is vendored with an exact version, commit and per-file hashes in `routing.lock.json`. The harness rejects missing, modified or extra vendor files. This is a reproducibility binding, not a signed attestation.

```sh
export GOTOOLCHAIN=local GOMAXPROCS=4 GOPROXY=off GOSUMDB=off
go test -mod=vendor ./...
go test -mod=vendor -race ./...
go vet -mod=vendor ./...
mkdir -p artifacts
sh scripts/build.sh transitbench "$PWD/artifacts/transitbench"
./artifacts/transitbench -fixture testdata/tiny.manifest.json \
  -repetitions 3 -warmups 1 -out artifacts/tiny.json
```

Run source-bound commands from this repository root. Outputs are created exclusively. The synthetic smoke workload checks functionality; its timings are not production performance estimates. Set `TRANSIT_BENCH_HARDWARE` explicitly if you want a machine description recorded by `familybench`; the repository contains no private machine fingerprint.

## Boundaries

`oracle/` enumerates bounded finite tiny instances and fails on truncation. `regression/` includes independent whole-word/event/vector specifications, hand-authored examples, metamorphic and batch-order checks, mutation controls and bounded fuzz targets. Walking tests use a separate Floyd–Warshall formulation. Reference generation does not import production search/pruning logic. Full-itinerary validation remains separate from search. Tests cannot guarantee bug freedom.

The local strict-identity CSA and independent-request shared scan are research controls. They do not reproduce an external production beam search, within-request candidate-stop batching or a station-selection/ranking service. No performance equivalence or loss claim about any external system is made. A future heuristic adapter needs its own explicit generic configuration and validation scope.

`cmd/familybench` records complete raw/final/display witnesses, resources, preparation and core/response/batch boundaries for supported adapters. Profile, transfer-aware, Core-CH and ULTRA commands retain separate entrypoints. `candidateprobe` requires explicitly supplied data and cases; no real-world cases are bundled.

Read [the evaluation protocol](docs/EVALUATION.md). Aggregate historical results and their limits are in [the research checkpoint](results/checkpoint-20261020/RESULTS_AND_STATUS.md). Raw full-model reports, operator timetables, OSM extracts/graphs, private screenshots and derived real-data queries are excluded. You must establish data rights and record input hashes before supplying any external dataset. A source's software MIT license does not automatically license its timetable data.

## Research checkpoint reproduction

The scoped familybench adapters cover capped ordinary TB, capped ULTRA control/safe subset, static-role-cap FLASH, experimental fixed-cap TP and mandatory-verified static-cap T-REX. Dense RAPTOR/McRAPTOR retain their named Early Pruning adapters. Read [adapter configuration and outcome contracts](docs/RESEARCH_CHECKPOINT.md).

```sh
sh scripts/reproduce-checkpoint.sh /absolute/path/to/new-smoke-directory
```

The Python 3 wrapper builds a source-bound binary and checks nine isolated tiny synthetic runs, complete raw/final witnesses, valid-empty versus declined/not-run outcomes and forced deadlines. It requires no keys, signup or network. It is functionality evidence, not a load benchmark or reproduction of excluded full-model inputs.
