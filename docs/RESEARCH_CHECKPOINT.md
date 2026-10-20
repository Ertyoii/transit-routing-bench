# Public research checkpoint

This composition retains the published harness and adds scoped public adapters. The original static finite graph, clocks, transfer/staying-aboard rules, identity, role/total walking resources, accessibility and truncation contracts remain in the routing module's contract documents. No private routing implementation or its policies/evidence are admitted.

## Reproduce the tiny examples

Run `sh scripts/reproduce-checkpoint.sh /absolute/path/to/new-directory` from this checkout. Python 3 and Go 1.27.x are required. All dependencies are vendored; the script disables module network access. Files are created exclusively in the new output directory, plus ignored build caches. Nine source-bound processes exercise the following names:

| Name | Config in testdata/scoped-config | Contract |
|---|---|---|
| raptor_early | none | Earliest arrival representatives |
| mc_raptor_early | none | Arrival/boarding/walking frontier representatives |
| trip_based_capped | tb.json | Unranked arrival/boarding representatives with independent role caps |
| ultra_transfer_complete_capped | ultra-control.json | Transfer-complete control |
| ultra_cap_safe_stay_witness_subset_v1 | ultra-subset.json | Sufficient safe omission subset |
| flash_tb_static_stop_pair_suffix_flags_role_caps_v1 | flash.json | Static stop-pair suffix flags and role caps, fresh profiles only |
| tp_destination_fixed_caps_experimental | tp.json and tp-partial.json | Fixed destination/walking class; partial preparation cannot serve |
| trex_static_caps_mandatory_verified_experimental | trex.json | Every unrestricted representative replayed; bounded independent enumeration/frontier agreement mandatory |

Scoped adapters require explicit `-scoped-config` input with exactly one algorithm configuration. Walking caps come from queries; they are never silently widened. T-REX requires positive verification limits. The named FLASH adapter rejects retained-profile policies so experimental TP support cannot change the qualified adapter's meaning.

Two separately named [non-CSA qualification v2 adapters](NON_CSA_QUALIFICATION_V2.md) add an explicit retained TP origin domain and fixed-transfer-cap ranked T-REX with defined-probe verification. Their configuration, completion and cost units are distinct. The [instrumented campaign report](../results/non-csa-qualification-v2/RESULTS_AND_STATUS.md) records scoped positive and bounded negative results, with [subsequent native status](../results/non-csa-qualification-v2/EVIDENCE_SCOPE.md). Confidence intervals, general full-model/production qualification and repository CI/workflow coverage remain unmet.

The CC0 scoped fixture has a zero-access query whose feasible arrival is 30, a broader-access query whose arrival is 20, and an unreachable query. The unrestricted ranked T-REX candidate hides the narrow query's feasible slower route and must decline with cleared output. Independent bounded enumeration demonstrates the hidden route. The routing module also contains equal-objective and other walking-role counterexamples.

## Evidence and outcomes

`familybench` retains raw, final validated and displayed results per query, algorithm details, preparation costs, core times, common-submission response times, batch makespan and resource snapshots. Shared batch core time is never divided into a fabricated query latency. Summary latency distributions are explicitly conditional; attempted, not-run, completed, valid-empty and transit denominators are retained. A completed entirely walking journey need not be a transit result.

Preparation-unavailable slots are `not_run_preparation_unavailable`. T-REX distinguishes `unsupported_cap_certificate`, `incomplete_ranked_work`, `incomplete_verification`, correctness mismatch and successful complete/empty results. These rejected/incomplete states cannot claim route completeness. The process-level `success` flag means no malformed output/unknown adapter failure was detected; it does not mean every requested query was supported or completed. Forced-deadline passes remain separate from measured repetitions.

Preparation is classified before slot formatting. Unexpected constructor/adapter/configuration failures set `preparation.process_fatal=true`, `success=false` and exit nonzero after retaining every not-run slot. Typed context cancellation/deadline, capability declines and resource-exhaustion/guard errors recognized by authoritative library prefixes have `preparation.expected_skip=true` and retain their nonfatal policy. A malformed configuration mentioning a budget is a failure, not evidence of exhaustion. Unrecognized preparation errors fail by default. Exposed configuration is checked before construction resource guards: nested FLASH budgets, T-REX explicit partition and mandatory verification settings, ULTRA query limits and legacy positive flags cannot be hidden by an earlier resource decline. `go test -mod=vendor ./cmd/familybench -run '^TestPreparationProcessOutcomes$' -count=1` exercises the real source-bound CLI for the two reported v4 failures, an unknown name containing diagnostic-looking words, invalid and masked nested configurations, valid positive resource guards, partial TP, deadline and capability controls (27 cases, including a valid capability decline with diagnostic-looking input identity). The independent v4 review returned NO PUBLISH for this defect; the repaired snapshot requires re-review.

The capped verifier shares no ranked search/pruning logic, but derives from the benchmark oracle. Agreement with that same oracle is not a second independent verification; literal expected witnesses and separately authored witness checks remain important.

## Historical results and limits

The [aggregate status report](../results/checkpoint-20261020/RESULTS_AND_STATUS.md), JSON matrix, CSV and evidence identities preserve successful short-load results as well as failed/incomplete T-REX and TP qualification. Historic metrics bind separately measured sources. Final composed-source tests do not remeasure that matrix, and this tiny smoke reproduction is not a performance qualification.

T-REX raw coverage fails for binding caps: filtering infeasible winners cannot recover missing feasible objectives. Its original panel certified zero answers. TP full-source preparation, finalization, retained-memory feasibility and serving latency remain unqualified; the approximate nine-hour source-local planning estimate does not justify an automatic all-source build. These limitations are part of the published research result.

The unofficial Singapore model is frequency-derived with approximate walking. OSM alone is not a timetable, and route/headway data is not an exact departure schedule. Input hashes identify excluded evidence without granting redistribution rights or making the full-model campaign reproducible from this checkout. Regional acceptance, physical accessibility, production SLAs and maximum-efficiency claims remain open. Passing tests cannot guarantee bug freedom.
