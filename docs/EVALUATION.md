# Reproducible evaluation contract

Freeze source revision, binary fingerprint, dependency lock, dataset/query hashes, service date, IANA timezone, seeds, tie/identity semantics, objective and resource limits before evaluating. Runtime clock, feed updates and local timezone must not change a frozen query. Preserve >24h service events and explicit trip instances. Same-vehicle continuation is distinct from boarding; transfer walking overlaps a transfer minimum rather than necessarily adding to it. Pickup/dropoff, accessibility and absorbing destination rules apply to full itineraries.

## Separate claims

1. Earliest arrival: one feasible optimal arrival under the supported model.
2. Pareto: all nondominated declared objective vectors, with representative versus all-identity coverage explicit.
3. Strict identity top-k: the first k feasible identities under the declared total order, with an actual completeness argument.
4. Bounded presentation: a finite pool of feasible displayed candidates, without an implicit global top-k claim.

A per-stop beam, bounded event scan, objective pruning or early stopping is heuristic unless a separate proof applies. Display caps, a scalar ranking penalty and batching do not change that status. Local research controls are not proxies for undocumented production code. Independent-request batches and candidate stop-pair batches within a passenger request need separate workload definitions and timing boundaries.

## Correctness evidence

Use an independent tiny-instance exhaustive oracle that does not share production search/pruning logic. Explicit state/journey/leg limits define the tested scope; enumeration truncation fails rather than returning an apparent complete reference. Validate every output itinerary independently, including partial-search candidate pools, and recompute clocks, identity, resources and objective values. Model correctness, candidate quality and operational performance are separate scorecards.

Test literal boundaries, ties, loops, >24h clocks, calendars, staying aboard, boarding/alighting restrictions, transfer precedence, walking roles, destination absorption and unknown accessibility. Add input permutations, batch size/order invariance and monotonicity checks appropriate to each contract. Bound fuzz duration and parallelism; run race checks. Tests cannot guarantee bug freedom.

Agreement between implementations is useful evidence, but shared representations and helpers can cause common errors. Do not treat agreement or a supplied feasible witness as an independent full-network optimum certificate. Recall/regret claims require a compatible reference; an incomplete reference cannot certify unreachable requests or zero regret. Report unknowns and unsupported profiles explicitly.

## Measurement

Run one isolated algorithm/scenario per process and serialize CPU-intensive campaigns. Keep warmups separate, preserve every repetition and query result, and retain failures in request denominators. Never replace a failed row with an easier query or silently expand its budget. Report scenario/stratum selection before observing outcomes; diagnostic cases are not demand samples.

Record load, preprocessing, graph/provider acquisition, checker preparation, core search, full response, serialization, allocations and memory separately. Response starts at submission and includes queueing, reconstruction, validation and ranking. Shared batches have makespan and throughput; dividing makespan by batch size does not give individual latency. Shared per-query core latency may be unavailable and must remain null. Whole-pass throughput includes failed work and between-batch bookkeeping before separately measured serialization. Cumulative allocations are not retained heap or peak RSS. Sampled safety stops are not hard resource confinement.

Keep completed latency distributions alongside requested/completed/failed counts. Use paired workload comparisons and query/OD-cluster resampling where departures share origins/destinations. Throughput intervals should use repetition as the sampling unit. State confidence-interval method, seed, sample size and limitations; small local samples do not establish production tail latency or SLAs.

Real-data validation is limited by source truth. OSM is not a timetable, headways are not exact departures, and frequency expansions must remain labeled models. Accessibility and physical walking reachability require evidence beyond mathematical graph optimality. Data redistribution requires separate source-specific permission and attribution; no data right follows from this repository's code license.
