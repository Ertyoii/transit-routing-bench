# Singapore public-model routing benchmark results

Status: all predeclared heldout runs and aggregate analyses are complete and independent evidence acceptance passed on 2026-10-21. Publication review remains separate. This is a bounded best-measured snapshot, not protocol/global convergence.

## Headline and scope

The separately sealed public-model test ran 76 fresh processes in 19 subcampaigns: 48 primary processes (12 configurations × four windows, 450 requests each) and 28 native-screen processes (four strict-CSA adapters plus three same-query point anchors × four windows, 90 requests each). All 24,120 ordinary offered rows completed. These are configuration executions on shared frozen cohorts, not 24,120 distinct demand queries. Another 24,120 forced-deadline controls are separately labeled; zero warmups. Controls are never included in these ordinary totals or quantiles. No test-triggered source, budget, selector, query filtering or retry was used.

These are finite stop-pair queries against a community frequency-expanded timetable and conservative OSM-derived walking. They are not current official LTA service, live API latency, actual passenger demand, verified physical reachability or an independently exhaustive full-network oracle. See [methodology](METHODOLOGY.md) for native contracts, exact splits, timing exclusions and data assumptions.

There are 27 implemented native entrypoints with deliberately unequal evidence levels. Eight native point-frontier entrypoints have 450 test requests/window (some with baseline/candidate source controls); four strict-CSA entrypoints have 90/window. Auxiliary profile/range/TAD smoke, graph-only CoreCH, unsupported semantics and preprocessing-limited attempts remain separate. OpenTripPlanner is absent. See [evidence levels](EVIDENCE_LEVELS.md), the inventory JSON and retained failure records; a 12-query smoke is not qualified as a 450-query tail study.

## Primary heldout response latency

Morning has 450 requests. The 2D outputs classify 204 as transit, three as all-walk and 243 as valid model-empty. McRAPTOR retains transit alternatives on all 207 nonempty requests, so its transit-conditioned cohort is not identical to the 2D cohort. Never delete model-empty or difficult rows to manufacture a favorable latency.

All rows below completed 450/450. Times are empirical nearest-rank p50/p95/p99 in milliseconds, from common in-process submission through queueing/search/reconstruction/checking/ranking/quality. Input loading, router/checker/quality-index preparation, artifact serialization and transport are excluded and reported separately. Each process serves the whole workload; this is not a new cold process per individual request.

| Native configuration | Offered response p50 | p95 | p99 | Transit-only p50 | p95 | p99 |
|---|---|---|---|---|---|---|
| RAPTOR Early baseline | 46.78 | 91.05 | 106.15 | 41.70 | 91.05 | 99.98 |
| RAPTOR Early dense + walking | 33.78 | 61.27 | 70.49 | 31.22 | 59.04 | 69.80 |
| EA-CSA baseline | 68.97 | 108.28 | 126.37 | 75.43 | 111.95 | 125.92 |
| EA-CSA dense + walking | 36.06 | 60.25 | 77.61 | 40.64 | 63.83 | 77.60 |
| Capped ULTRA control baseline | 27.42 | 59.55 | 67.98 | 19.66 | 56.15 | 66.68 |
| Capped ULTRA control dense | 16.57 | 33.47 | 45.71 | 14.75 | 31.46 | 47.21 |
| Capped ULTRA safe-subset dense | 16.81 | 32.64 | 38.42 | 13.96 | 34.57 | 39.29 |
| McRAPTOR dense 500k + finite20 | 54.51 | 93.01 | 110.55 | 59.27 | 95.27 | 110.47 |
| McRAPTOR Early dense 500k + finite20 | 50.85 | 86.99 | 103.43 | 51.00 | 89.37 | 102.42 |
| Capped Trip-Based 100m transfers | 69.20 | 195.93 | 269.87 | 53.22 | 167.78 | 251.21 |
| Ordinary RAPTOR baseline | 54.26 | 89.42 | 111.02 | 59.24 | 90.82 | 111.02 |
| Ordinary RAPTOR dense + walking | 39.36 | 63.26 | 80.17 | 43.75 | 67.18 | 84.08 |

Within each frozen native-contract source pair, the dense variants preserve emitted witnesses/status/certificates on all 7,200 offered test comparisons across 16 window-pairs, with zero recorded differences or unknown pairs. This is differential evidence, not full-network completeness proof. Morning p95 decreases by 32.71% for RAPTOR Early, 44.36% for EA-CSA and 43.79% for capped ULTRA control. The richer 3D McRAPTOR row is not an equal-work or equal-quality comparison with a 2D frontier.

Four windows remain separate, not independent population samples. The next table lists offered-response p95; full p50/p95/p99, transit cohorts, failures and resources are in FULL_TEST_METRICS.json.

| Configuration | Morning p95 ms | Midday | Evening | Overnight |
|---|---|---|---|---|
| RAPTOR Early baseline | 91.05 | 83.49 | 90.64 | 48.72 |
| RAPTOR Early dense + walking | 61.27 | 60.95 | 62.02 | 34.21 |
| EA-CSA baseline | 108.28 | 107.41 | 109.11 | 57.89 |
| EA-CSA dense + walking | 60.25 | 56.27 | 59.55 | 33.01 |
| Capped ULTRA control baseline | 59.55 | 55.45 | 57.36 | 28.74 |
| Capped ULTRA control dense | 33.47 | 34.32 | 32.75 | 15.07 |
| Capped ULTRA safe-subset dense | 32.64 | 33.65 | 32.84 | 15.56 |
| McRAPTOR dense 500k + finite20 | 93.01 | 92.41 | 88.49 | 45.72 |
| McRAPTOR Early dense 500k + finite20 | 86.99 | 86.33 | 90.37 | 42.44 |
| Capped Trip-Based 100m transfers | 195.93 | 133.77 | 156.03 | 46.47 |
| Ordinary RAPTOR baseline | 89.42 | 91.75 | 93.15 | 54.82 |
| Ordinary RAPTOR dense + walking | 63.26 | 63.85 | 64.00 | 35.73 |

## Startup, allocations and memory are not hidden

Morning measured components below are separate from response. Startup is the sum of instrumented input-load/router/checker/quality-index phases only, not full launch-to-first-byte latency. Hashing, OS-page state, uninstrumented gaps and transport are outside this sum. RSS is sampled whole process-group peak in decimal GB, not a per-query allocation figure; the 7 GiB Go target is soft and no hard dedicated-core/cgroup isolation is claimed. Allocation is measured batch allocation divided by offered attempted requests, not retained memory.

| Configuration | Startup phase sum s | First response ms | Router / checker / quality prep s | Query allocation MB/request | Peak RSS GB | Quality-phase p95 ms |
|---|---|---|---|---|---|---|
| RAPTOR Early baseline | 8.348 | 65.32 | 2.389 / 1.765 / 1.637 | 24.57 | 1.36 | 0.670 |
| RAPTOR Early dense + walking | 7.892 | 48.98 | 2.663 / 1.449 / 1.448 | 12.03 | 1.33 | 0.676 |
| EA-CSA baseline | 6.224 | 85.68 | 1.769 / 1.229 / 1.028 | 26.46 | 1.26 | 0.668 |
| EA-CSA dense + walking | 6.048 | 44.82 | 1.853 / 1.158 / 1.101 | 12.65 | 1.15 | 0.673 |
| Capped ULTRA control baseline | 7.244 | 51.68 | 2.144 / 1.449 / 1.487 | 4.97 | 1.33 | 0.669 |
| Capped ULTRA control dense | 6.478 | 31.58 | 2.097 / 1.010 / 1.214 | 5.62 | 1.32 | 0.721 |
| Capped ULTRA safe-subset dense | 6.342 | 27.47 | 2.051 / 1.102 / 1.120 | 5.46 | 1.35 | 0.695 |
| McRAPTOR dense 500k + finite20 | 6.382 | 62.03 | 2.058 / 1.082 / 1.127 | 13.38 | 1.44 | 1.888 |
| McRAPTOR Early dense 500k + finite20 | 6.394 | 62.94 | 1.877 / 1.116 / 1.273 | 13.85 | 1.31 | 1.619 |
| Capped Trip-Based 100m transfers | 15.951 | 93.23 | 8.737 / 2.858 / 2.198 | 22.13 | 5.70 | 0.767 |
| Ordinary RAPTOR baseline | 6.426 | 66.37 | 1.884 / 1.393 / 1.137 | 25.75 | 1.22 | 0.661 |
| Ordinary RAPTOR dense + walking | 6.410 | 45.76 | 1.803 / 1.395 / 1.109 | 11.94 | 1.31 | 0.688 |

Dense capped ULTRA improves response but increases transient query allocation, so it is not advertised as a memory win. The 100-million retained-transfer operating point for capped Trip-Based retains about 87.8 million actual transfer links and incurs substantial construction/memory costs; its ceiling is not merely a work counter. Cumulative heap/resource snapshots overlap and must not be summed. The finite20 quality phase computes k3+k5 selection and anchor controls together, not top-3-only cost.

## Primary heldout quality

The common observed witness pool is nonempty for 720 of 1,800 requests/configuration, giving 14,400 query × hypothetical-weight slots. All 1,080 model-empty requests/configuration remain in outcome denominators but have no finite preference optimum. Every completed output is independently reconstructed against the finite model. Pool agreement/no observed counterexample is not an exhaustive search proof.

The 20 score hypotheses are elapsed time plus transfer penalties 0/150/300/600/900 seconds and extra-walking weights 0/1/2/4. Walking already contributes to elapsed time. These are not authenticated human preferences or population probabilities. Coverage and regret are relative to this incomplete same-contributor pool. Score-second regret is not necessarily actual travel-time regret.

| Native candidates / default display | Raw coverage | Default top3 | Default top5 | Max raw / top3 / top5 regret (score-s) |
|---|---|---|---|---|
| Ordinary RAPTOR | 65.26% | 65.07% | 65.26% | 4184 / 4184 / 4184 |
| RAPTOR Early | 65.26% | 65.07% | 65.26% | 4184 / 4184 / 4184 |
| EA-CSA | 65.15% | 64.97% | 65.15% | 4184 / 4184 / 4184 |
| Capped ULTRA control | 65.26% | 65.07% | 65.26% | 4184 / 4184 / 4184 |
| Capped ULTRA safe subset | 65.26% | 65.07% | 65.26% | 4184 / 4184 / 4184 |
| Capped Trip-Based | 55.49% | 55.31% | 55.49% | 6260 / 6260 / 6260 |
| McRAPTOR | 100.00% | 90.96% | 97.47% | 0 / 2603 / 2186 |
| McRAPTOR Early | 100.00% | 90.96% | 97.47% | 0 / 2603 / 2186 |

The separately frozen finite_preferences_v2 selector is optimized to the SAME 20 hypothetical evaluation weights, not a heldout preference model. For both McRAPTOR entrypoints:

| Display policy | Top3 coverage | Max top3 regret | Top5 coverage | Max top5 regret |
|---|---|---|---|---|
| Default | 90.96% | 2603 | 97.47% | 2186 |
| finite20 (same grid) | 97.12% | 406 | 99.83% | 106 |

Walking-tie differences explain why arrival/boarding-cap agreement need not imply equal preference quality; EA-CSA and capped Trip-Based are not silently given RAPTOR walking choices. Native 3D raw pool coverage 100% means no observed-pool regret in this tested grid, not global optimality.

## Strict CSA native90 heldout comparison

The strict-CSA cohort is every frozen screen-test request, 90/window: 360 per adapter across four windows, with the same 90 point-anchor requests. All 2,520 native/anchor rows completed. Single-request versus shared-scan at batch1 agreed on all 720 complete paired native outputs. Batch1 tests compatibility, not an assumed batching benefit. Arrival returns one identity-top10 lane; score runs boarding-cap lanes 0–4, each k10 with a one-million-label ceiling, and validates/ranks their union. It is not a 2D/3D Pareto contract or necessarily only ten returned identities.

Morning native90 contains 35 transit and 55 valid-empty outputs per adapter. These empirical p99s have only 90 observations and cannot be treated as 450-query or production-tail qualification.

| Native configuration | p50 ms | p95 | p99 | Startup phase sum s | Peak RSS GB |
|---|---|---|---|---|---|
| CSA arrival, single-request | 220.00 | 467.81 | 814.04 | 6.364 | 1.19 |
| CSA score, single-request | 614.45 | 899.89 | 1248.15 | 6.033 | 1.26 |
| CSA arrival, shared batch1 | 229.00 | 444.31 | 775.80 | 6.546 | 1.27 |
| CSA score, shared batch1 | 609.10 | 930.72 | 1294.11 | 6.576 | 1.16 |
| RAPTOR Early dense anchor | 29.83 | 73.93 | 93.57 | 7.159 | 1.34 |
| Capped ULTRA dense anchor | 13.65 | 35.48 | 51.31 | 6.649 | 1.34 |
| McRAPTOR Early dense finite20 anchor | 38.43 | 91.32 | 111.97 | 6.144 | 1.34 |

Its separate pool is nonempty for 121/360 requests, giving 2,420 eligible weight slots. This pool/cohort must not be substituted for the full-panel pool.

| Native candidates / display | Raw coverage | Default top3 | Default top5 |
|---|---|---|---|
| CSA arrival, single-request | 61.82% | 58.22% | 59.50% |
| CSA score, single-request | 81.74% | 63.14% | 65.95% |
| CSA arrival, shared batch1 | 61.82% | 58.22% | 59.50% |
| CSA score, shared batch1 | 81.74% | 63.14% | 65.95% |
| RAPTOR Early dense anchor | 63.35% | 63.35% | 63.35% |
| Capped ULTRA dense anchor | 63.35% | 63.35% | 63.35% |
| McRAPTOR Early dense finite20 anchor | 100.00% | 89.17% | 95.45% |

The frozen same-grid finite20 Mc anchor covers 96.61% at top 3 and 99.79% at top 5, with maximum pool-relative regret 325/71 score-seconds. Large-model evaluation does not independently rederive strict identity-topk; the separate tiny exhaustive/specification source oracles qualify that contract within their tested scope.

## Retained validation, negative and unavailable results

- Primary validation has 21,600 complete rows. The original runner stopped after 44/48 processes on a relative support-artifact path before four capped Trip-Based processes began. Those four were run in a fresh unchanged-native continuation with only the support path absolute-corrected. Original runner_error, unstarted slots and continuation origins remain distinct; no original completed status was fabricated.
- Original native90 validation has 1,438/1,440 CSA rows complete, with one genuine score-single morning deadline and one score-shared midday deadline. The predeclared clean timing replication completed 90/90 but does not replace the original 89/90. These failures remain in validation quality and outcome denominators. Test completion does not erase validation failures.
- Native batch4/8 includes negative results. Arrival shared-scan was slower; score-shared batch8 completed 0/12 offered smoke requests at the common 3-second deadline. Cooperative cancellation responses could exceed 3 seconds. Batch makespan is not divided into per-query latency.
- Larger Mc label ceilings and larger transfer-index budgets are explicit resource-quality operating points, not free source speedups. The small default Mc label budget initially failed some requests; 500k/1m candidates were frozen before heldout testing.
- Legacy bare Trip-Based has an adapter-specific 900-second transfer-walking radius and hits its 5-million-transfer preparation guard. It was not falsely labeled GTFS-rule unsupported. The successful 100m result is the distinct capped 600 variant, not a larger-budget bare 900 run.
- Legacy FLASH, transfer patterns, scalable TP and TREX reject nonempty GTFS rules. Scoped full-metric FLASH/TREX hit a full-walking-closure guard. Initial malformed fixed-cap TP policies and corrected closure/25m/100m retained-transfer declines are preserved. Ranked TREX's original RSS stop leaves 12 unresolved requests; unresolved is not valid-empty or an explicit algorithm decline.
- ProfileCSA/rangeRAPTOR complete 48 native tune-smoke profiles each, where one profile covers every integer readiness in a 61-time interval. Morning whole-profile medians were about 342.79/104.47 ms respectively, not divided by 61. TAD completes 48 one-EA native smoke requests, about 39.38 ms morning, while reference frontier work is richer. Canonical native ULTRA is unavailable on all 48 offered smoke requests because the transfer-rule contract is unsupported; rules were not removed.
- CoreCH is transfer-graph-only, not transit routing. The initial self-only 24-anchor smoke is trivial. The frozen 117-anchor screen keeps 117 whole rows and 13,689 target cells per method/window, including 105 self-only rows and 12 with positive nonself reachability. Independent raw-edge Bellman-Ford audit found agreement; roughly 0.032 ms identity versus 0.033 ms CH row medians did not demonstrate a speedup.
- Rail-entry/exit walking sensitivity is a separate hypothesized model: 2,880/2,880 four-window tune rows complete, without merging its witnesses, splits, quality pool or qualification into primary results. More modeled paths do not prove better real-world service.

## Optimization boundary and reproducibility

This is a bounded best-measured source/configuration snapshot. The declared finite convergence protocol, including equal-budget rounds without a new qualifying Pareto improvement, is NOT satisfied; global convergence is also false. Transfer-index compression, alternative preparation data structures, generic walking-metric variants, resource tiers, external preferences and external systems remain unexhausted. Fixed heldout execution order is not randomized; two reversed-order repeated tune blocks provide supporting conditional process observations, not host-noise/population confidence.

The source bundle supplies 16 complete baseline-to-candidate/overlay patches, exact offline tree replays, source/build/config hashes, public retrieval checks and portable normalization/walking/workload/evaluator/runner helpers. Baselines are public MIT repositories Ertyoii/transit-routing-bench and Ertyoii/transit-routing-go; the latter's '-go' suffix is required. Raw/complete derived GTFS/OSM/LTA databases, native binaries and credentials are not redistributed. Third-party source rights/notices remain applicable.

Published outcome projections keep every offered status and diagnostic control, objective metrics and witness hashes while withholding full underlying witness legs and replacing execution-local paths. They are not byte-identical raw full passes. Original file hashes remain indexed. Reconstructing omitted witnesses requires authorized retrieval and rerunning the supplied pipeline. Fresh hardware needs new environment/seal bindings; reproducibility does not imply identical timings. No source/config changes or retries may be selected from these exposed test results in this release.
