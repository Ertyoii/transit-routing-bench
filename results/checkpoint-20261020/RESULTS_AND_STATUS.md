# Algorithm results and status — research checkpoint

This is an aggregate research snapshot, subject to final composed-release review. Dense RAPTOR/McRAPTOR, ordinary capped Trip-Based, ULTRA subset and FLASH scoped short-load evidence have independent scoped review. FLASH’s grouping correction is closed. **TP v8 telemetry and T-REX v6 storage/accounting are independently accepted within scope; capped T-REX qualification failed. The subsequent TP sample and T-REX cap diagnosis await their own reviews.** The composed release integrates the scoped public implementations, with portable synthetic reproductions. Historical measurements bind their original source identities; the final composition has not been rerun under the full-model load matrix.

## Current panel and outcome status

| Implementation | Contract | Current outcome | External query accounting | Review status |
|---|---|---|---|---|
| Dense RAPTOR EP | Arrival/boardings representatives | Full panel and short load qualified within scope | 128/128 per panel: 86 transit, 42 empty; 3,150/3,150 measured valid | Accepted scoped evidence |
| Dense McRAPTOR EP | Arrival/boardings/walking representatives | Full panel and short load qualified within scope | 128/128 per panel: 86 transit, 42 empty; 3,150/3,150 measured valid | Accepted scoped evidence |
| Capped ordinary Trip-Based | Unranked arrival/boardings representatives | Full panel and short load qualified within scope | 3,150/3,150 measured valid: 2,117 transit, 1,033 empty | Independently reviewed scoped evidence |
| ULTRA safe pruning subset | Arrival/boardings representatives; sufficient certificates | Full panel and short load qualified within scope | 384/384 native attempts; 3,150/3,150 measured valid | Accepted scoped evidence |
| ULTRA complete control | Arrival/boardings representatives | Functional control only | 384/384 native attempts: 258 transit, 126 empty; no separate nine-cell load | Accepted control evidence |
| Conservative FLASH suffix flags | Unranked arrival/boardings representatives | Full panel and short load qualified within scope | 384/384 native attempts; 3,150/3,150 measured valid; 3 measured arrivals exceed 200 ms | Accepted scoped evidence and corrected grouping |
| Fixed-destination/cap TP v8 | Arrival/boardings representatives | Global index incomplete: 1/5,449 sources | 1,450 internal profiles complete; 128 external queries not run | Scoped accounting accepted |
| Ranked/static capped T-REX v6 | Sufficient certificate plus mandatory verifier | Index complete; no certified answers | Retry: 384 attempted, 384 declined, 0 certified, 0 not run; prior attempt: 384 not run | Scoped accounting accepted |

`algorithm-status.json` also records every other algorithm family advertised in the published baseline: earliest-arrival CSA, public finite-k/heuristic CSA controls, profile CSA/RAPTOR variants, legacy TB/FLASH/TP, scalable TP, transfer-aware Dijkstra and Core-CH. No new current-panel/load result is admitted for those rows. “No current result” does not mean an algorithm is unsupported or incorrect. Public CSA controls remain separate from the excluded private CSA implementation.

## Reviewed short-load aggregates

Each method has three repetitions at 5, 10 and 20 offered requests/second: 5 seconds warmup and 30 seconds measured per run. The fixed policy is 4 CPUs, 8,000,000,000 bytes hard memory, no extra swap, four workers, queue capacity 1,024 and a 5-second whole-request deadline. Each method has 3,150 measured arrivals, 2,117 transit and 1,033 valid empty results; warmup is separate. All distinct retained witnesses remain certified online and replayed offline.

Latency is intended arrival through receipt of the complete valid response. p99 ranges below are ranges of three per-run success-conditioned p99 values, **not confidence intervals**. No batch makespan is divided by query count. `load-summary.csv` preserves available transit-conditioned p99 ranges, preparation ranges and peak memory separately.

| Method | QPS | Valid / offered | Transit / empty | Valid ≤200 ms / offered | Valid ≤500 ms / offered | Conditional p99 range, ms | Whole preparation, s | Peak cgroup GB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Dense McRAPTOR EP | 5 | 450/450 | 298/152 | 450/450 | 450/450 | 93.68–97.65 | 1.424–1.469 | 0.732 |
| Dense McRAPTOR EP | 10 | 900/900 | 611/289 | 900/900 | 900/900 | 79.46–85.32 | 1.402–1.571 | 0.757 |
| Dense McRAPTOR EP | 20 | 1800/1800 | 1208/592 | 1800/1800 | 1800/1800 | 67.23–71.11 | 1.450–1.556 | 0.787 |
| Dense RAPTOR EP | 5 | 450/450 | 298/152 | 450/450 | 450/450 | 72.50–80.35 | 1.438–1.583 | 0.761 |
| Dense RAPTOR EP | 10 | 900/900 | 611/289 | 900/900 | 900/900 | 69.23–71.46 | 1.417–1.456 | 0.740 |
| Dense RAPTOR EP | 20 | 1800/1800 | 1208/592 | 1800/1800 | 1800/1800 | 47.84–51.92 | 1.463–1.507 | 0.792 |
| Capped ordinary Trip-Based | 5 | 450/450 | 298/152 | 450/450 | 450/450 | 112.02–118.78 | 2.463–2.566 | 2.543 |
| Capped ordinary Trip-Based | 10 | 900/900 | 611/289 | 900/900 | 900/900 | 91.64–115.63 | 2.456–2.525 | 2.790 |
| Capped ordinary Trip-Based | 20 | 1800/1800 | 1208/592 | 1800/1800 | 1800/1800 | 89.29–91.53 | 2.444–2.555 | 2.817 |
| ULTRA safe pruning subset | 5 | 450/450 | 298/152 | 450/450 | 450/450 | 70.19–72.51 | 1.506–1.529 | 0.829 |
| ULTRA safe pruning subset | 10 | 900/900 | 611/289 | 900/900 | 900/900 | 66.09–69.33 | 1.486–1.555 | 0.789 |
| ULTRA safe pruning subset | 20 | 1800/1800 | 1208/592 | 1800/1800 | 1800/1800 | 46.22–49.87 | 1.488–1.500 | 0.744 |
| FLASH conservative suffix flags | 5 | 450/450 | 298/152 | 450/450 | 450/450 | 179.50–187.66 | 9.214–10.131 | 4.032 |
| FLASH conservative suffix flags | 10 | 900/900 | 611/289 | 898/900 | 900/900 | 176.87–185.64 | 9.259–9.922 | 4.036 |
| FLASH conservative suffix flags | 20 | 1800/1800 | 1208/592 | 1799/1800 | 1800/1800 | 161.11–171.30 | 9.628–9.950 | 4.369 |

Whole preparation and lifetime peak memory use each campaign’s declared boundary; neither cumulative allocated bytes nor a sampled heap is live retained-index memory. Preparation boundaries and guards differ between methods. These observations do not isolate causal speedups. Three short repetitions give descriptive and unstable repetition intervals, not reliable long-run tail confidence. Within-run intervals were withheld with only three ten-second blocks. An observed [1,1] success interval is not future certainty. Complete control was not separately load-tested against the ULTRA subset; a lower latency cannot be attributed to its 375 deleted walking pairs.

Dense tables add about 2.14 MB of observed live heap and regress sparse-query allocation: approximately 1.7 KB to 268 KB for RAPTOR and 1.4 KB to 337 KB for McRAPTOR, with median core latency increasing by a few microseconds in the diagnostic sparse probes. This is a workload-dependent tradeoff, not a universal optimization.

The original dense campaign has an interrupted attempt with 600 planned measured slots and 84 warmup slots whose schedule/outcome accounting is incomplete. Sixteen observed client responses pass replay, but this attempt is outside the 6,300 verified completed-matrix arrivals across the two dense methods. No all-attempt dense success fraction is claimed. FLASH has 3,750 measured arrivals across attempts: 3,150 verified completed-matrix arrivals plus 600 client-completed but deployment-unverified arrivals from the interrupted attempt. The latter have 100 additional warmup arrivals and are retained separately. These historical attempts are not dropped or relabeled as verified successes.

## Pending preparation and negative qualification

**TP v8:** one fixed-destination/cap source completed all 1,450 profiles in 61.345 seconds of constructor time, including 55.859 seconds of native profiling. It visited 5,815,467,802 transfers and emitted 12 independently replayed feasible patterns. These witness checks do not establish profile completeness. Global source coverage is 1/5,449; 5,448 sources remain. All 128 external queries are not run. A one-source mean-rate scenario is not a complete-index prediction or lower bound; the subsequent prespecified multi-source sample is described below; shared-work changes remain unimplemented. Constructor cumulative allocation was 33,571,115,824 bytes; whole-process peak cgroup memory was 3,999,670,272 bytes. These are preparation costs, not serving latency.

**TP v9 planning sample:** ten prespecified sources across five strata completed all 2,838 exact profiles; all 44 emitted pattern witnesses independently replayed. Each isolated source index remains globally incomplete. The same 128 external identities are not run in each process (1,280 not-run slots); there is no serving-latency sample. The stratified estimate for this one destination/cap class is 8.997 hours of source-local wall work, with a small-sample approximate planning interval 7.395–10.598 hours (effective degrees of freedom 2.885). Median common setup is 5.332 seconds, added once; final incidence is unmeasured. The prior lexical-source pilot is excluded from this estimator. This fresh-source additive scenario does not predict long-process GC/DAG growth, full-index peak memory or provide guaranteed 95% coverage. Largest isolated peak was 4.033 GB. No source was retried/replaced and no all-source build was launched. Estimated source-local transfer work is 2.125 trillion visits; current retained graph guards and memory still need a full-scope plan. Source-selection instrumentation preserves all 56 baseline differential records, passes focused race tests, and rejects two deliberate behavioral errors. This new stage awaits review; it is not a new public algorithm or a speedup comparison with the profiled pilot.

**T-REX v6:** the retry constructed its full index in 265.107 seconds; index plus certificate preparation took 265.714 seconds, and the additional checker took 0.386 seconds. Peak cgroup memory was 6,383,960,064 bytes with no recorded OOM. Full index counts are 54,502,751 transfers, 113,305 event runs, 9,278,171 compact proofs and 63,818,078 overlay entries. The previous attempt also completed the index, then cancelled during additional-checker preparation; its 384 scheduled query slots are not run. The retry uses the same routing source and original caps, with a lower Go memory target and explicit phase reclamation.

| Retry outcome | Per 128-query pass | Across 3 passes | Reference transit / empty per pass | Interpretation |
|---|---:|---:|---:|---|
| Unrestricted representative fails original walking cap | 11 | 33 | 11 / 0 | Certificate coverage failure; feasible reference routes exist for all 11 |
| Ranked query work guard exhausted | 41 | 123 | 34 / 7 | Incomplete at 2,000,000 work units; no correctness mismatch follows from exhaustion alone |
| Mandatory verifier scan guard exhausted | 76 | 228 | 41 / 35 | Incomplete at 4,000,000 scans; no correctness mismatch follows from exhaustion alone |
| Certified transit | 0 | 0 | — | No accepted frontier to claim reference agreement |
| Certified empty | 0 | 0 | — | Empty result arrays on rejected calls are not no-route answers |
| Not run in retry | 0 | 0 | — | Prior attempt’s 384 not-run slots remain separate |

All three query orders produced the same outcomes. Across the two attempts there are 768 scheduled slots: 384 not run and 384 declined. All-offered certified attainment ≤200 ms and ≤500 ms is 0/128 per retry pass and 0/384 over the retry. Success-conditioned/transit-conditioned latency quantiles are undefined; useful certified throughput is zero. Decline durations are deliberately omitted from the successful performance table. Raising only work budgets cannot make the current sufficient-condition certificate accept its fixed cap-violating representatives. A separate full-model diagnostic now splits the eleven cap declines: six have feasible raw subsets equal to the frozen capped reference frontier, while five lack a required reference objective in the raw candidates. Each absent objective is dominated by an infeasible unrestricted representative. All eleven public outputs remain unchanged declines, so no incorrect route was returned. The diagnosis independently replayed 20 raw witnesses (seven feasible) and 27 reference witnesses. It awaits review and is not another qualification pass. Filtering raw candidates cannot recover the five missing objectives; general ranked support for binding walking caps remains explicitly unsupported. The 41 ranked and 76 verifier budget failures remain unresolved, not correctness mismatches.

## Model and claims boundary

The fixed model is service date 2026-10-16, Asia/Singapore, seconds 25,200–32,400. It contains 270,441 connections, 5,450 stops, 12,685 used trips and 3,294 directed footpaths, including restricted pickup/dropoff behavior and 70 static stop-pair minimum-transfer rules. It is an unofficial frequency model for bus and rail with approximate walking. LTA routes/headways are not exact scheduled departures, and OSM is not a timetable.

All 128 queries retain 900-second intermediate walking. The 118 ordinary queries use 600-second access/egress and 900-second direct walking; ten targeted queries use zero access/egress/direct walking. Ordinary queries allow four boardings, 3,900 seconds total walking and 1,024 legs; nine targeted queries allow two boardings and one allows one boarding, with 900 seconds total walking. The feasibility transfer buffer is zero; the 300-second ranking penalty is separate. Earliest arrival, Pareto vectors, strict top-k identities and bounded candidate display remain different contracts. No physical accessibility, live disruption, fare, all-GTFS or other-country qualification follows. Singapore validation does not advance the regional gate.

Original operator/derived inputs, raw query identities, itineraries, local reports and private system details are excluded. Dataset/query hashes in the JSON identify retained evidence; they do not grant distribution rights or make the real-data campaign reproducible from this checkout. Aggregate source identities are in `evidence-identities.json`; final public evidence packaging needs explicit review. Passing tests, independent witnesses and cross-method agreement cannot guarantee bug freedom.
