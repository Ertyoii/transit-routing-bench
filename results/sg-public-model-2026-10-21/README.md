# Singapore public-model routing benchmark · 2026-10-21

A reproducible, bounded benchmark and optimization snapshot, not an official Singapore service feed or a global-optimality claim.

## Read the results

- [Results, latency/quality/resource tables and failures](RESULTS.md)
- [Methodology, native contracts, splits and timing boundaries](METHODOLOGY.md)
- [All 27 implemented native entrypoints and unequal evidence levels](EVIDENCE_LEVELS.md)
- [Source reconstruction, complete patches and input retrieval](repro/README.md)
- [Compact independent evidence acceptance summary](evidence/reports/PUBLIC_EVIDENCE_ACCEPTANCE.json)
- [Machine-readable complete file manifest](FILE_MANIFEST.json)
- [Outcome shard index and exact row-order bindings](evidence/SHARD_INDEX.json)
- [Projection accounting/hash verification](PUBLICATION_ACCOUNTING_CHECK.json)
- [How to reassemble independently decompressable outcome shards](publication-tools/SHARD_PUBLICATION_OUTCOMES.md)

The sealed heldout slate completed all 24,120 ordinary offered rows across 76 fresh processes. These are configuration executions on shared frozen cohorts, not 24,120 distinct passenger-demand queries. Another 24,120 forced-deadline controls are separate. Source-paired emitted outputs agree on 7,200 primary and 720 strict-CSA comparisons. Independent finite-model witness, timing, quantile, resource and common-pool checks passed.

Morning's primary 450-query response p50/p95/p99: dense capped ULTRA control 16.57/33.47/45.71 ms; dense RAPTOR Early 33.78/61.27/70.49 ms; dense+walking EA-CSA 36.06/60.25/77.61 ms. Richer 3D McRAPTOR Early with finite20 selection is 50.85/86.99/103.43 ms. Those are distinct native contracts and quality levels, not an equal-quality league table. Startup phase sums are separately about 6–8 seconds for these morning configurations, not included in response and not complete launch-to-first-byte latency.

On the same 20 explicitly hypothetical preference weights and an incomplete observed witness pool, McRAPTOR raw candidates cover 100% of observed optima; default top3 covers 90.96%, frozen same-grid finite20 top3 covers 97.12%. This is not measured human preference quality or global completeness. Native strict CSA has a separate 90-query/window cohort and identity-topk/score-cap-union semantics; all failures, negative batching results, unsupported contracts and preparation limits remain visible.

## Package layout and retained limits

- `repro/`: sixteen complete base-to-candidate/overlay patches, source pins, exact offline tree replays, licenses, retrieval/hash checks and portable preparation/workload/evaluator/runner/analysis helpers. Public bases are `Ertyoii/transit-routing-bench` and `Ertyoii/transit-routing-go`.
- `evidence/`: 46 independently decompressable outcome shards (each under 1 MiB), portable execution provenance, aggregate metrics/quality/optimization/split summaries and original evidence hash references. The shard index preserves all 179,516 projected rows in exact original stream order across 51 retained campaigns; these include repeated/configuration/diagnostic/prelaunch slots, not new demand. Ordinary, forced, warmup, preparation-unavailable, prelaunch and unresolved rows retain their roles; they must not be pooled into successful latency.
- Full witness legs, verbose selection features/preparation proof payloads, raw or complete derived timetable/map databases and executable binaries are not redistributed. Their original hashes remain bound; compact projections differ in byte hashes from originals. Reproduction requires authorized source retrieval and rerunning the supplied pipeline.

Community frequency expansion, incomplete walking/anchor assumptions and the finite stop-pair workload limit external validity. Fresh processes do not imply cold disk or exclusive hardware. Empirical p99s are not production/SLA tails. The declared finite convergence protocol remains unmet and global convergence is false; remaining implementation/resource/quality space is explicit. No test-triggered retuning or retry was used.

This directory is a result/source supplement under the existing repository license, with preserved third-party notices. It is not a source-data redistribution license. See `repro/DATA_RIGHTS_AND_LIMITATIONS.md` before retrieving research inputs.
