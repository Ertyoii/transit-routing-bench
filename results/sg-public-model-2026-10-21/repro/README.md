# Singapore campaign source reproducibility supplement

Status: frozen source snapshot. Changes create a new snapshot and require fresh manifests. The combined release supplies accepted reports and its combined release manifest outside repro/.

This source-only supplement accompanies the 2026-10-21 public-modeled Singapore campaign. It is not a data release, production router, complete-network correctness certificate, latest-official-service baseline, or claim that every adapter is optimized.

## What is reproducible

Sixteen complete patches are included: fourteen candidate patches, one eight-file auxiliary overlay and one four-file diagnostic profiling overlay.

- Fourteen complete `git diff --binary --full-index` patches reconstruct seven routing/benchmark candidate pairs from the public base commits recorded in `SOURCE_PINS.json`. Added source and test files are included. Patches were not sanitized: all original patch bytes passed the portable-path scan.
- Each routing patch includes its tests/documentation; each benchmark patch includes its actual vendored routing changes and lock. No giant duplicate vendor tree is packaged.
- Offline temporary-index replay produced exactly the frozen Git tree for every candidate, including new files. All fourteen original worktrees were clean and their HEADs matched the requested pins when packaged. The manifest also records the byte-oriented source digests used by the benchmark.
- The complete auxiliary eight-file patch replays on the benchmark base, matches its working-source blobs, and has source SHA256 `ae087ee05d0dcd85eb7925fa912f749184e6db81b83df67205e4aa89427e1c63`. It is a working-source overlay, not a clean committed candidate.
- Frozen helper sources cover import/normalization metadata, conservative OSM walking generation, separate rail sensitivity, workload generation/binding, evaluation, registry/finalist/public-model gates, foreground runner, 20 static configuration source snapshots and analysis. Configurations retain explicitly declared source/target domain constants as program configuration, not a redistributed endpoint workload. Local helper original and portable byte hashes and every portability edit are in `SOURCE_PINS.json`.

`PAYLOAD_MANIFEST.json` lists exact relative path, byte size and SHA256 for every source payload file except itself and its detached checksum. `SHA256SUMS` checks the manifest bytes; it is not a digital signature. `SOURCE_PINS.json` separates connector-verified public base evidence from local exact-tree/working-overlay source identities. `VALIDATION.json` distinguishes performed checks from unperformed build/data/timing work.

## Public bases versus local candidate source identities

The correct routing repository is https://github.com/Ertyoii/transit-routing-go, not a repository inferred by stripping its `-go` suffix. The benchmark repository is https://github.com/Ertyoii/transit-routing-bench. The release owner verified public GitHub commit metadata for both pinned base commits and exact trees; see `PUBLIC_BASE_VERIFICATION.json`. That remote reachability evidence is separate from this packager's offline source-tree patch replay. Candidate commits remain local frozen identities unless separately published. No Go module import path was changed to match a repository URL.

## Source reconstruction

Requires Python 3.10+, Git, and independently installed Go 1.27.3 when you later build. No Go toolchain, binary, package cache or vendor snapshot is shipped; the public benchmark base already carries its pinned vendor source. Relevant optional walking/parser validation package versions are in `helpers/walking-build/requirements-reproduction.txt`; it is not a transitive wheel/hash lock.

Choose a fresh writable research root, then run from this bundle directory:

```sh
export SG_ROOT="$PWD/reproduction"
python scripts/reconstruct_sources.py --variant baseline
python scripts/install_helpers.py
python scripts/verify_patches.py --base-root "$SG_ROOT"
python scripts/reconstruct_sources.py --variant csa-opt
```

Other candidate IDs: `query-walk-opt`, `eacsa-opt`, `walk-eacsa-opt`, `raptor-dense-opt`, `walk-opt`, `ultra-capped-opt`; auxiliary ID: `auxiliary-source-v2`. Each creates new routing/benchmark directories. Use `--local-bases DIR` for reconstruction without network, where DIR has the two pinned public base repositories. Reconstructing a source-identical patched tree does not recreate a candidate commit, its author metadata, or its public reachability. Do not cherry-pick one candidate patch on another: every patch is independently relative to its declared public base.

Source trees, helper snapshots and baseline vendor must remain separate. The benchmark is built from its vendored routing source, not whichever sibling routing directory happens to exist. `scripts/sourcehash.py` independently implements the documented Go source hash algorithm and runs no Go code.

## Diagnostic profiling-driver overlay

`patches/bench-profiling-driver-overlay.patch` includes all four dirty working-source files from `bench-profile`, including the two formerly untracked Go files. It was captured using a temporary Git index/object store without changing the live checkout, then independently replayed against the public benchmark base and compared to every captured file byte. Exact working-source SHA256 and resulting Git tree are recorded under `diagnostic_overlays` in `SOURCE_PINS.json`. This is not a clean committed candidate.

`PROFILING_OVERLAY_HISTORICAL_BINDING.json` checks all six original `profile-tune-six` command and summary artifacts: each `sources_before` Go hash and embedded build/runtime hash equals the current overlay's Go source SHA256, with runtime/build and executable bindings consistent. Exact command/summary byte hashes are recorded without copying those raw artifacts. The recorded Go source hash excludes README and arbitrary support files. Therefore historical full-tree/README byte identity is not proven; matching dirty filenames do not establish it, and no README/support-only drift is asserted absent or present.

Use `python scripts/reconstruct_sources.py --variant profiling-driver-overlay` to reconstruct this diagnostic source. Its `profile-tune-six` profiles cover whole-process diagnostic work and must not be treated as headline routing latency, a new optimization, or an additional benchmark result. This packager ran no Go, test, router or profiling load. Actual `.pprof`/`.cpuprofile` artifacts and all profile binaries are excluded.

## Obtain research inputs separately

Read `DATA_RIGHTS_AND_LIMITATIONS.md` and the preserved provider notices first. This package includes URLs/hashes and attribution, not authorization to redistribute source or derived data. Retrieval is explicit, not run during packaging:

```sh
python scripts/retrieve_inputs.py --accept-provider-terms
# Later, verify existing inputs without any network access:
python scripts/retrieve_inputs.py --verify-only
```

The script allows only pinned HTTPS sources, rejects an unexpected redirect scheme, enforces exact byte size and SHA256, does not overwrite different existing data, and removes only partial files it created. If a source is withdrawn or changed, retrieval fails closed; do not substitute newer bytes under the old hashes. Provider availability and terms were not rechecked during offline packaging.

## Reproduce preparation after obtaining inputs lawfully

These are future reproduction commands, not work executed by this source packager. They may require substantial memory and runtime. Do not overlap preparation/builds/tests with timed campaigns.

1. Source `$SG_ROOT/setup/environment.sh` after installing Go. Calculate the baseline source digest with `python scripts/sourcehash.py "$SG_ROOT/bench" > "$SG_ROOT/setup/bench-build-source-sha256.txt"`. Run `bash "$SG_ROOT/data/import-public-windows.sh"`. It verifies raw GTFS bytes and uses the public `cmd/gtfsimport` with `deterministic_model`, `modeled_snapshot`, `minimum_time_proxy`, the fixed windows and fail-not-truncate connection cap. Weekend absence stays a coverage limitation.
2. The installed `data/NORMALIZED_INPUTS.json` is aggregate historical metadata and expected hashes, not dataset bytes. Check each locally regenerated dataset against `INPUT_ARTIFACT_EXPECTATIONS.json`. Metadata paths are materialized under SG_ROOT; rebuild audit/seal hashes when paths differ. Do not pretend its historic audit hashes identify new audit bytes.
3. From `$SG_ROOT/walking-build`, run in order `python build_walk.py parse`, `python parse_relations.py`, `python build_walk.py connect`, `python generate_footpaths.py --limit 0 --cap 600 --out conservative600`. Optional separate rail sensitivity: `python build_rail_sensitivity.py`, `python generate_rail_sensitivity.py`. Run `python validate_artifacts.py` only after both layers exist, then `python merge_datasets.py --rail-overlap-policy preserve-gtfs`. The merge preserves original GTFS proxies and explicitly records excluded overlapping rail-model pairs. Go loader/checker helper sources and module metadata are included; these were not built here.
4. From `$SG_ROOT/workload-build`, regenerate the plan with `python generate_workloads.py plan --gtfs-zip ../data/singapore-gtfs-v2026-07-12.zip --window-plan ../data/window-plan.json --out NEW_PLAN`. The generator is byte-identical to the frozen v2 snapshot. Compare `NEW_PLAN/HASH_COMMITMENT.json` with the bundled commitment. Default cluster/split/window choices are deterministic and output-independent. No frozen endpoint plan, stop metadata or bound workload is redistributed here.
5. Create a local JSON mapping from each window ID to its regenerated dataset path. Bind a new directory with `python generate_workloads.py bind --plan NEW_PLAN/planned-workload.json --datasets YOUR_MAPPING.json --out NEW_BOUND`. Never edit a historic workload to replace its dataset hash. Use separate mapping/output for each walking variant.
6. Use the included `setup/run_campaign.py --help`, `setup/campaign_gate.py` and `evalkit/evalkit.py --help`. Register regenerated workloads; freeze actual source/configuration finalists; create a new seal and verify the public-model gate before any heldout execution. The original runner requires four logical CPUs 0–3, preserves failures and offered rows, and serializes through its timing lock. GOMEMLIMIT is a soft GC target, not a hard RSS bound. Source-only packaging did not execute these steps or verify end-to-end data replay.
7. Build benchmark commands using the reconstructed benchmark's own source-bound `scripts/build.sh`, not an unbound ad-hoc binary. Keep raw outcomes/failed denominators local. Analysis snapshots include `summarize_campaigns.py`, `compare_optimization.py`, `analyze_repeated_blocks.py`, `summarize_quality_windows.py` `analyze_primary_stage.py` and `analyze_native_csa_stage.py`. These support explicit multi-subcampaign provenance and separate joint-complete versus deadline-censored comparisons; a continuation must not be reported as if an earlier interrupted campaign completed.

Portable helpers and generated manifests can contain a new root, helper digest, timestamp or runtime measurement. These are new artifacts. Their hashes/seals must be recomputed; neither source-equivalent reproduction nor aggregate agreement proves identical timing or global routing optimality. The source-only `prepare_final_test_release.py` and `execute_final_test_release.py` helpers are included for review, but neither was run by the source packager; no seal, release plan generation or heldout launch occurred here.

The separately frozen publication projection (`stage_publication.py`, SHA256 `633ec9c0daf180131c4aed8a87e3f55047b414384551f56b803b490d0289afbe`) its 23-test synthetic suite and `COMPACT_PROJECTION.md` are included unchanged; no actual projection was run during source packaging. Optional compact mode consolidates or hashes verbose metadata while retaining outcomes, objective vectors, witness hashes, timings and failures; full mode remains available.

## Licensing and release boundaries

Repository MIT licenses, third-party source notices and attribution inventories are retained in `licenses/`. Existing data/provider notices remain separate. Original campaign helper source is included within the existing MIT-licensed project under that repository default, as confirmed by the project owner. The identical project MIT notice is copied to this supplement's LICENSE. Preserved third-party notices remain applicable; MIT does not extend to third-party source or derived transit/map data.

No raw/derived GTFS or OSM datasets, map assets, stop metadata, endpoint workloads, binaries, original machine logs, internal task status, checkpoints, conversations, credentials or private absolute paths are part of this payload. See the validation summary for scan scope and remaining limitations.
