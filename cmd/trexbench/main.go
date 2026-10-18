// trexbench measures T-REX query variants and an independently prepared RAPTOR.
package main

import (
	"context"
	"flag"
	"fmt"
	"math/rand/v2"
	"os"
	"path/filepath"
	"reflect"
	"runtime"

	"github.com/ertyoii/transit-routing-bench/evaluation"
	"github.com/ertyoii/transit-routing-bench/experiment"
	"github.com/ertyoii/transit-routing-bench/fixtures"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/paper"
	"github.com/ertyoii/transit-routing-go/presentation"
	"github.com/ertyoii/transit-routing-go/raptor"
	"github.com/ertyoii/transit-routing-go/strictjson"
	"github.com/ertyoii/transit-routing-go/tripbased"
	"github.com/ertyoii/transit-routing-go/validate"
	"strings"
	"time"
)

type item struct {
	Stratum string      `json:"stratum"`
	Query   model.Query `json:"query"`
}
type workload struct {
	Seed          uint64 `json:"seed"`
	Method        string `json:"method"`
	DatasetSHA256 string `json:"dataset_sha256"`
	Items         []item `json:"items"`
}
type record struct {
	item
	Raw                  []model.Journey             `json:"raw"`
	Final                []model.Validated           `json:"final"`
	Complete             bool                        `json:"complete"`
	Unsupported          bool                        `json:"unsupported"`
	TimedOut             bool                        `json:"timed_out"`
	Error                string                      `json:"error,omitempty"`
	CoreNS               int64                       `json:"core_ns"`
	ResponseNS           int64                       `json:"response_ns"`
	Allocated            uint64                      `json:"core_allocated_bytes"`
	Stats                any                         `json:"stats"`
	Display              map[int]presentation.Result `json:"display_options"`
	SubmissionResponseNS int64                       `json:"submission_response_ns"`
	Batch                int                         `json:"batch"`
}
type pass struct {
	Algorithm  string   `json:"algorithm"`
	Repetition int      `json:"repetition"`
	Warmup     bool     `json:"warmup"`
	Records    []record `json:"records"`
	Batches    []any    `json:"batches"`
}

func read(p string, v any) (string, error) {
	b, e := os.ReadFile(p)
	if e != nil {
		return "", e
	}
	e = strictjson.Decode(b, v)
	return fixtures.Sum(b), e
}
func vector(q model.Query, v []model.Validated) []int64 {
	out := make([]int64, q.MaxBoardings+1)
	for i := range out {
		out[i] = paper.Infinity
	}
	for _, j := range v {
		for b := j.Metrics.Boardings; b < len(out); b++ {
			out[b] = min(out[b], j.Metrics.Arrival)
		}
	}
	return out
}

var algorithms = []string{"trex_overlay", "trex_rank_test", "trex_unranked", "unaccelerated_raptor"}
var comparisonAlgorithms = algorithms

func run() error {
	dp := flag.String("dataset", "", "normalized dataset")
	qp := flag.String("queries", "", "frozen queries")
	out := flag.String("out-dir", "", "new output directory")
	reps := flag.Int("repetitions", 3, "measured passes")
	warmups := flag.Int("warmups", 1, "retained warmup passes")
	deadline := flag.Duration("timeout", 5*time.Second, "per-query cooperative deadline")
	prepDeadline := flag.Duration("prep-timeout", 30*time.Second, "per-preparation deadline")
	levels := flag.Int("levels", 3, "nested binary partition levels; zero is unpartitioned control")
	maxWork := flag.Int("max-work", 200000000, "construction counted-work limit")
	maxRuns := flag.Int("max-runs", 100000, "event-TB run limit")
	maxTransfers := flag.Int("max-transfers", 500000, "transfer limit")
	maxOverlays := flag.Int("max-overlay-entries", 2000000, "stored overlay transfer IDs")
	maxWitnesses := flag.Int("max-witnesses", 1000000, "retained traversal witnesses")
	batchSize := flag.Int("batch-size", 1, "independent point queries submitted together and served sequentially; not shared search")
	hardware := flag.String("hardware", "unrecorded", "verified hardware")
	flag.Parse()
	if *dp == "" || *qp == "" || *out == "" || *reps < 1 || *warmups < 0 || *deadline <= 0 || *prepDeadline <= 0 || *batchSize < 1 {
		return fmt.Errorf("invalid arguments")
	}
	if e := os.Mkdir(*out, 0700); e != nil {
		return e
	}
	prov, e := experiment.Identify(".")
	if e != nil {
		return e
	}
	if !prov.RuntimeMatchesBuild {
		return fmt.Errorf("build through scripts/build.sh")
	}
	start := time.Now()
	var d model.Dataset
	var work workload
	dh, e := read(*dp, &d)
	if e != nil {
		return e
	}
	qh, e := read(*qp, &work)
	if e != nil {
		return e
	}
	if work.DatasetSHA256 != dh || len(work.Items) == 0 {
		return fmt.Errorf("dataset/query binding mismatch or empty workload")
	}
	loadNS := time.Since(start).Nanoseconds()
	seen := map[string]bool{}
	if e = d.Validate(); e != nil {
		return e
	}
	for _, i := range work.Items {
		if seen[i.Query.ID] {
			return fmt.Errorf("duplicate query")
		}
		seen[i.Query.ID] = true
		if e = i.Query.Validate(d); e != nil {
			return e
		}
	}
	cfg := tripbased.TREXConfig{Levels: *levels, MaxBoardings: 4, Limits: tripbased.TREXLimits{MaxStops: 10000, MaxTrips: 100000, MaxInputEdges: 1000000, MaxClosurePaths: 1000000, MaxWalkSettled: 2000000, MaxTransfers: *maxTransfers, MaxRuns: *maxRuns, MaxWork: *maxWork, MaxWitnesses: *maxWitnesses, MaxOverlayEntries: *maxOverlays, MaxQueuedSegments: 1000000, MaxQueryWork: 1000000}}
	prep := map[string]any{}
	prepErrors := map[string]error{}
	var before, after runtime.MemStats
	prepare := func(name string, fn func(context.Context) error) {
		runtime.GC()
		runtime.ReadMemStats(&before)
		start = time.Now()
		ctx, cancel := context.WithTimeout(context.Background(), *prepDeadline)
		err := fn(ctx)
		elapsed := time.Since(start).Nanoseconds()
		if err == nil && (ctx.Err() != nil || elapsed > prepDeadline.Nanoseconds()) {
			err = fmt.Errorf("preparation cooperative deadline exceeded")
		}
		cancel()
		runtime.ReadMemStats(&after)
		prepErrors[name] = err
		message := ""
		if err != nil {
			message = err.Error()
		}
		prep[name] = map[string]any{"elapsed_ns": elapsed, "allocated_bytes": after.TotalAlloc - before.TotalAlloc, "complete": err == nil, "error": message, "resources": experiment.SnapshotResources()}
		fmt.Printf("%s preparation %.3fs error=%s\n", name, float64(elapsed)/1e9, message)
	}
	var x *tripbased.TREXIndex
	prepare("trex_overlay", func(ctx context.Context) error { var err error; x, err = tripbased.BuildTREX(ctx, d, cfg); return err })
	for _, name := range []string{"trex_rank_test", "trex_unranked"} {
		prepErrors[name] = prepErrors["trex_overlay"]
		prep[name] = map[string]any{"shared_preparation": "trex_overlay", "scope": "query ablation on identical prepared transfer set; full preparation not an independently optimized TB preparation cost"}
	}
	io, e := experiment.WriteArtifact(filepath.Join(*out, "trex-index.json"), x.Snapshot())
	if e != nil {
		return e
	}
	prep["index_io"] = io
	var baseline *raptor.Index
	prepare("unaccelerated_raptor", func(ctx context.Context) error { var err error; baseline, err = raptor.New(d); return err })
	runtime.ReadMemStats(&before)
	start = time.Now()
	checker, e := validate.New(d)
	if e != nil {
		return e
	}
	elapsed := time.Since(start).Nanoseconds()
	runtime.ReadMemStats(&after)
	prep["independent_checker"] = map[string]any{"elapsed_ns": elapsed, "allocated_bytes": after.TotalAlloc - before.TotalAlloc, "resources": experiment.SnapshotResources()}
	measure := func(name string, i item, timeout time.Duration) record {
		r := record{item: i, Raw: []model.Journey{}, Final: []model.Validated{}, Display: map[int]presentation.Result{}}
		if e := prepErrors[name]; e != nil {
			r.Error = "preparation unavailable: " + e.Error()
			r.Unsupported = strings.Contains(r.Error, "capability:")
			return r
		}
		ctx, cancel := context.WithTimeout(context.Background(), timeout)
		defer cancel()
		var before, after runtime.MemStats
		runtime.ReadMemStats(&before)
		t := time.Now()
		var err error
		if name == "unaccelerated_raptor" {
			result, e := baseline.Search(ctx, i.Query)
			err = e
			r.Raw = result.Journeys
			r.Complete = result.Complete
			r.Stats = result.Stats
		} else {
			var result tripbased.TREXResult
			switch name {
			case "trex_overlay":
				result, err = x.Search(ctx, i.Query)
			case "trex_rank_test":
				result, err = x.SearchRanked(ctx, i.Query)
			case "trex_unranked":
				result, err = x.SearchUnranked(ctx, i.Query)
			}
			r.Raw = result.Journeys
			r.Complete = result.Complete
			r.Stats = result.Stats
		}
		r.CoreNS = time.Since(t).Nanoseconds()
		runtime.ReadMemStats(&after)
		r.Allocated = after.TotalAlloc - before.TotalAlloc
		r.TimedOut = ctx.Err() != nil || r.CoreNS > timeout.Nanoseconds()
		if err == nil && r.TimedOut {
			err = fmt.Errorf("cooperative deadline exceeded")
		}
		t = time.Now()
		if err == nil && r.Complete {
			for _, j := range r.Raw {
				v, e := checker.Check(i.Query, j)
				if e != nil {
					err = e
					break
				}
				r.Final = append(r.Final, v)
			}
		}
		if err == nil && r.Complete {
			for _, k := range []int{1, 3, 5, 10} {
				display, e := presentation.Rank(i.Query, r.Final, k, 300)
				if e != nil {
					err = e
					break
				}
				r.Display[k] = display
			}
		}
		r.ResponseNS = r.CoreNS + time.Since(t).Nanoseconds()
		if err != nil {
			r.Error = err.Error()
			r.Complete = false
			r.Unsupported = strings.Contains(r.Error, "capability:")
			r.Final = []model.Validated{}
			r.Display = map[int]presentation.Result{}
		}
		return r
	}
	summaries, comparisons := []any{}, []any{}
	throughput := map[string][]float64{}
	success := true
	for rep := 0; rep < *warmups+*reps; rep++ {
		items := append([]item{}, work.Items...)
		rng := rand.New(rand.NewPCG(work.Seed, uint64(rep)))
		rng.Shuffle(len(items), func(i, j int) { items[i], items[j] = items[j], items[i] })
		names := append([]string{}, algorithms...)
		shift := rep % len(names)
		names = append(names[shift:], names[:shift]...)
		paired := map[string]map[string]record{}
		for _, name := range names {
			p := pass{Algorithm: name, Repetition: rep, Warmup: rep < *warmups, Records: []record{}, Batches: []any{}}
			paired[name] = map[string]record{}
			supported, unsupported, failed := 0, 0, 0
			cores, responses := []float64{}, []float64{}
			allocated := uint64(0)
			start = time.Now()
			for batchBegin := 0; batchBegin < len(items); batchBegin += *batchSize {
				batchEnd := min(batchBegin+*batchSize, len(items))
				submitted := time.Now()
				batchComplete := 0
				coreSum := int64(0)
				ids := []string{}
				for _, i := range items[batchBegin:batchEnd] {
					r := measure(name, i, *deadline)
					r.Batch = batchBegin / *batchSize
					r.SubmissionResponseNS = time.Since(submitted).Nanoseconds()
					ids = append(ids, i.Query.ID)
					coreSum += r.CoreNS
					if r.Complete {
						batchComplete++
					}
					p.Records = append(p.Records, r)
					paired[name][i.Query.ID] = r
					allocated += r.Allocated
					if r.Complete {
						supported++
						cores = append(cores, float64(r.CoreNS))
						responses = append(responses, float64(r.SubmissionResponseNS))
					} else if r.Unsupported {
						unsupported++
					} else {
						failed++
						if prepErrors[name] == nil {
							success = false
						}
					}
				}
				p.Batches = append(p.Batches, map[string]any{"batch": batchBegin / *batchSize, "query_ids": ids, "requested": batchEnd - batchBegin, "complete": batchComplete, "makespan_ns": time.Since(submitted).Nanoseconds(), "sum_core_ns": coreSum, "scheduler": "independent point calls served sequentially from common submission"})
			}
			makespan := time.Since(start).Nanoseconds()
			file := fmt.Sprintf("%s-pass-%02d.json", name, rep)
			io, e := experiment.WriteArtifact(filepath.Join(*out, file), p)
			if e != nil {
				return e
			}
			qps := float64(supported) * 1e9 / float64(makespan)
			summaries = append(summaries, map[string]any{"algorithm": name, "repetition": rep, "warmup": p.Warmup, "file": file, "sha256": io.SHA256, "requested": len(items), "supported_complete": supported, "unsupported": unsupported, "failed": failed, "supported_core_ns": evaluation.Summarize(cores), "supported_response_ns": evaluation.Summarize(responses), "all_attempts_allocated_bytes": allocated, "makespan_ns": makespan, "supported_queries_per_second": qps})
			if !p.Warmup {
				throughput[name] = append(throughput[name], qps)
			}
			fmt.Printf("%s pass=%d requested=%d supported=%d unsupported=%d failed=%d makespan=%.3fs\n", name, rep, len(items), supported, unsupported, failed, float64(makespan)/1e9)
		}
		assessed, equal := 0, 0
		details := []any{}
		for _, i := range work.Items {
			available, same := true, true
			vectors := map[string][]int64{}
			errors := map[string]string{}
			var reference []int64
			for _, name := range comparisonAlgorithms {
				r := paired[name][i.Query.ID]
				available = available && r.Complete
				v := vector(i.Query, r.Final)
				vectors[name] = v
				errors[name] = r.Error
				if reference == nil {
					reference = v
				} else if !reflect.DeepEqual(reference, v) {
					same = false
				}
			}
			if available {
				assessed++
				if same {
					equal++
				} else {
					success = false
				}
			}
			details = append(details, map[string]any{"query_id": i.Query.ID, "assessed": available, "equal": available && same, "vectors": vectors, "errors": errors})
		}
		pairwise := []any{}
		for _, name := range algorithms {
			if name == "unaccelerated_raptor" {
				continue
			}
			a, eq := 0, 0
			rows := []any{}
			for _, i := range work.Items {
				r, b := paired[name][i.Query.ID], paired["unaccelerated_raptor"][i.Query.ID]
				available := r.Complete && b.Complete
				same := available && reflect.DeepEqual(vector(i.Query, r.Final), vector(i.Query, b.Final))
				if available {
					a++
					if same {
						eq++
					} else {
						success = false
					}
				}
				rows = append(rows, map[string]any{"query_id": i.Query.ID, "assessed": available, "equal": same})
			}
			pairwise = append(pairwise, map[string]any{"algorithm": name, "reference": "unaccelerated_raptor", "requested": len(work.Items), "assessed": a, "unavailable": len(work.Items) - a, "equal": eq, "details": rows})
		}
		comparisons = append(comparisons, map[string]any{"repetition": rep, "warmup": rep < *warmups, "requested": len(items), "assessed": assessed, "unavailable": len(items) - assessed, "equal": equal, "details": details, "pairwise": pairwise})

	}
	failures := []any{}
	for _, name := range append([]string{}, algorithms...) {
		for _, i := range work.Items {
			r := measure(name, i, time.Nanosecond)
			if r.Complete {
				success = false
			}
			failures = append(failures, map[string]any{"algorithm": name, "record": r})
		}
	}
	if _, e = experiment.WriteArtifact(filepath.Join(*out, "forced-deadlines.json"), failures); e != nil {
		return e
	}
	intervals := map[string]experiment.Interval{}
	if *reps >= 2 {
		for _, name := range append([]string{}, algorithms...) {
			ci, e := experiment.ThroughputConfidence(throughput[name], work.Seed)
			if e != nil {
				return e
			}
			ci.Statistic = "supported_queries_per_second_over_all_attempts_makespan"
			intervals[name] = ci
		}
	}

	_, e = experiment.WriteArtifact(filepath.Join(*out, "summary.json"), map[string]any{
		"success": success, "success_definition": "No mismatched accepted comparison or unexpected query failure; preparation/unsupported failures remain in every denominator.",
		"created_utc": time.Now().UTC().Format(time.RFC3339Nano), "provenance": prov, "dataset_sha256": dh, "queries_sha256": qh, "seed": work.Seed, "method": work.Method, "hardware": *hardware, "go_version": runtime.Version(), "goos": runtime.GOOS, "goarch": runtime.GOARCH, "logical_cpus": runtime.NumCPU(), "gomaxprocs": runtime.GOMAXPROCS(0), "input_load_ns": loadNS, "preparation": prep, "algorithms": algorithms, "comparison_algorithms": comparisonAlgorithms, "configuration": cfg, "dataset_counts": map[string]int{"stops": len(d.Stops), "trips": len(d.Trips), "connections": len(d.Connections), "footpaths": len(d.Footpaths)}, "query_timeout_ns": deadline.Nanoseconds(), "preparation_timeout_ns": prepDeadline.Nanoseconds(), "repetitions": *reps, "warmups": *warmups, "batch_size": *batchSize, "display_k": []int{1, 3, 5, 10}, "ranking_transfer_penalty": 300, "passes": summaries, "comparisons": comparisons, "throughput_intervals": intervals, "resources_final": experiment.SnapshotResources(), "scope": []string{
			"Static T-REX bounded positive transitive/nonbinding contract: nested partition, Event-TB ranks, basic LCL test, split-segment overlays. Unranked control shares preprocessing. Native partitioner, profiles and incremental updates remain open.",
			"Core includes guards, routing and full raw unpacking; response_ns adds independent validation and all four display selections. submission_response_ns additionally includes actual queue waiting and instrumentation since this batch's common submission. Per-query deadlines begin at service, not at batch submission.",
			"Independent sequential point scheduler: not shared multi-OD search. Batch makespan and per-request submission response are measured, never divided-time latency. Preparation and serialization are separate; whole-process RSS is cumulative and soft1GiB is not a hard per-index bound.",
			"Display k ranks supplied Pareto representatives only. It is not strict top-k or all-identity enumeration, may return fewer than k, and penalty300 never changes feasibility/time. Cross-family CSA batch/k-options evaluation remains separate.",
			"Public frequency-model data or explicitly synthetic fixtures; no exact Singapore/physical access or regional acceptance. Repetition bootstrap intervals are descriptive, not independent repeated preparation samples."}})
	if e != nil {
		return e
	}
	if !success {
		return fmt.Errorf("mismatch or unexpected failure; evidence retained")
	}
	return nil
}
func main() {
	if e := run(); e != nil {
		fmt.Fprintln(os.Stderr, e)
		os.Exit(1)
	}
}
