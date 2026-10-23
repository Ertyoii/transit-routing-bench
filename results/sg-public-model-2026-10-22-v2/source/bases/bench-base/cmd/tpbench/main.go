// tpbench compares basic Transfer Patterns, FLASH-TB, complete TB and RAPTOR.
package main

import (
	"context"
	"flag"
	"fmt"
	"github.com/ertyoii/transit-routing-bench/evaluation"
	"github.com/ertyoii/transit-routing-bench/experiment"
	"github.com/ertyoii/transit-routing-bench/fixtures"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/paper"
	"github.com/ertyoii/transit-routing-go/raptor"
	"github.com/ertyoii/transit-routing-go/strictjson"
	"github.com/ertyoii/transit-routing-go/tripbased"
	"github.com/ertyoii/transit-routing-go/validate"
	"math/rand/v2"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
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
	Raw         []model.Journey         `json:"raw"`
	Final       []model.Validated       `json:"final"`
	Complete    bool                    `json:"complete"`
	Unsupported bool                    `json:"unsupported"`
	TimedOut    bool                    `json:"timed_out"`
	Error       string                  `json:"error,omitempty"`
	CoreNS      int64                   `json:"core_ns"`
	ResponseNS  int64                   `json:"response_ns"`
	Allocated   uint64                  `json:"core_allocated_bytes"`
	Stats       any                     `json:"stats"`
	Graph       []tripbased.PatternEdge `json:"query_graph,omitempty"`
}
type pass struct {
	Algorithm  string   `json:"algorithm"`
	Repetition int      `json:"repetition"`
	Warmup     bool     `json:"warmup"`
	Records    []record `json:"records"`
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
func run() error {
	dp := flag.String("dataset", "", "normalized dataset")
	qp := flag.String("queries", "", "frozen queries")
	out := flag.String("out-dir", "", "new directory")
	reps := flag.Int("repetitions", 3, "measured passes")
	warmups := flag.Int("warmups", 1, "retained warmup passes")
	deadline := flag.Duration("timeout", 5*time.Second, "query deadline")
	prepDeadline := flag.Duration("prep-timeout", 180*time.Second, "preparation deadline")
	cells := flag.Int("cells", 1, "backend cells; basic TP requires one")
	maxWork := flag.Int("max-work", 200000000, "preparation work budget")
	maxRuns := flag.Int("max-runs", 10000, "global canonical-run budget")
	hardware := flag.String("hardware", "unrecorded", "verified host description")
	flag.Parse()
	if *dp == "" || *qp == "" || *out == "" || *reps < 1 || *warmups < 0 || *deadline <= 0 || *prepDeadline <= 0 {
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
		return fmt.Errorf("workload hash mismatch/empty")
	}
	loadNS := time.Since(start).Nanoseconds()
	seen := map[string]bool{}
	for _, i := range work.Items {
		if seen[i.Query.ID] {
			return fmt.Errorf("duplicate query")
		}
		seen[i.Query.ID] = true
		if e = i.Query.Validate(d); e != nil {
			return e
		}
	}
	profileCfg := tripbased.FlashConfig{Cells: *cells, MaxBoardings: 4, Limits: tripbased.FlashLimits{MaxStops: 10000, MaxTrips: 100000, MaxClosurePaths: 1000000, MaxWalkSettled: 2000000, MaxTransfers: 5000000, MaxRuns: *maxRuns, MaxWork: *maxWork, MaxFlagBytes: 100000000, MaxWitnesses: 1000000, MaxQuerySegments: 1000000}}
	cfg := tripbased.PatternConfig{Profile: profileCfg, MaxPatterns: 1000000, MaxNodes: 2000000, MaxEdges: 3000000, MaxDirectEntries: 5000000, MaxBuildWork: 200000000, MaxQueryWork: 1000000, MaxQueryLabels: 1000000}
	prep := map[string]any{}
	var before, after runtime.MemStats
	runtime.ReadMemStats(&before)
	start = time.Now()
	ctx, cancel := context.WithTimeout(context.Background(), *prepDeadline)
	x, buildErr := tripbased.BuildPatterns(ctx, d, cfg)
	buildNS := time.Since(start).Nanoseconds()
	cancel()
	runtime.ReadMemStats(&after)
	message := ""
	if buildErr != nil {
		message = buildErr.Error()
	}
	prep["transfer_patterns"] = map[string]any{"elapsed_ns": buildNS, "allocated_bytes": after.TotalAlloc - before.TotalAlloc, "complete": x.Complete() && buildErr == nil && buildNS <= prepDeadline.Nanoseconds(), "error": message, "resources": experiment.SnapshotResources()}
	io, e := experiment.WriteArtifact(filepath.Join(*out, "index.json"), x.Snapshot())
	if e != nil {
		return e
	}
	prep["index_snapshot_io"] = io
	if buildErr != nil || buildNS > prepDeadline.Nanoseconds() {
		failures := []record{}
		for _, i := range work.Items {
			failures = append(failures, record{item: i, Raw: []model.Journey{}, Final: []model.Validated{}, Error: "preparation unavailable: " + message, Unsupported: strings.Contains(message, "capability:")})
		}
		if _, e = experiment.WriteArtifact(filepath.Join(*out, "preparation-failures.json"), failures); e != nil {
			return e
		}
		_, e = experiment.WriteArtifact(filepath.Join(*out, "summary.json"), map[string]any{"success": false, "phase": "preparation", "provenance": prov, "dataset_sha256": dh, "queries_sha256": qh, "requested": len(work.Items), "assessed": 0, "unavailable": len(work.Items), "preparation": prep, "scope": "No partial index or query was accepted. Full denominator retained."})
		if e != nil {
			return e
		}
		return fmt.Errorf("preparation unavailable; full diagnostics saved")
	}
	fmt.Printf("Transfer Patterns preparation %.3fs patterns=%d nodes=%d edges=%d\n", float64(buildNS)/1e9, x.Snapshot().Stats.Patterns, x.Snapshot().Stats.Nodes, x.Snapshot().Stats.Edges)
	runtime.ReadMemStats(&before)
	start = time.Now()
	ctx, cancel = context.WithTimeout(context.Background(), *prepDeadline)
	control, controlError := tripbased.BuildFlash(ctx, d, profileCfg)
	cancel()
	elapsedControl := time.Since(start).Nanoseconds()
	runtime.ReadMemStats(&after)
	prep["flash_tb_control"] = map[string]any{"elapsed_ns": elapsedControl, "allocated_bytes": after.TotalAlloc - before.TotalAlloc, "resources": experiment.SnapshotResources()}
	if controlError != nil {
		return fmt.Errorf("matched control preparation: %w", controlError)
	}

	runtime.ReadMemStats(&before)
	start = time.Now()
	baseline, e := raptor.New(d)
	if e != nil {
		return e
	}
	elapsed := time.Since(start).Nanoseconds()
	runtime.ReadMemStats(&after)
	prep["unaccelerated_raptor"] = map[string]any{"elapsed_ns": elapsed, "allocated_bytes": after.TotalAlloc - before.TotalAlloc, "resources": experiment.SnapshotResources()}
	runtime.ReadMemStats(&before)
	start = time.Now()
	checker, e := validate.New(d)
	if e != nil {
		return e
	}
	elapsed = time.Since(start).Nanoseconds()
	runtime.ReadMemStats(&after)
	prep["independent_checker"] = map[string]any{"elapsed_ns": elapsed, "allocated_bytes": after.TotalAlloc - before.TotalAlloc, "resources": experiment.SnapshotResources()}
	measure := func(name string, i item, timeout time.Duration) record {
		r := record{item: i, Raw: []model.Journey{}, Final: []model.Validated{}}
		ctx, cancel := context.WithTimeout(context.Background(), timeout)
		defer cancel()
		var before, after runtime.MemStats
		runtime.ReadMemStats(&before)
		t := time.Now()
		var err error
		switch name {
		case "transfer_patterns":
			result, e := x.Search(ctx, i.Query)
			err = e
			r.Raw = result.Journeys
			r.Complete = result.Complete
			r.Stats = result.Stats
			r.Graph = result.Graph
		case "unaccelerated_raptor":
			result, e := baseline.Search(ctx, i.Query)
			err = e
			r.Raw = result.Journeys
			r.Complete = result.Complete
			r.Stats = result.Stats
		default:
			var result tripbased.Result
			if name == "flash_tb" {
				result, err = control.Search(ctx, i.Query)
			} else {
				result, err = control.SearchBaseline(ctx, i.Query)
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
		r.ResponseNS = r.CoreNS + time.Since(t).Nanoseconds()
		if err != nil {
			r.Error = err.Error()
			r.Complete = false
			r.Unsupported = strings.Contains(r.Error, "capability:")
			r.Final = []model.Validated{}
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
		names := []string{"transfer_patterns", "flash_tb", "tb_complete", "unaccelerated_raptor"}
		shift := rep % len(names)
		names = append(names[shift:], names[:shift]...)
		paired := map[string]map[string]record{}
		for _, name := range names {
			p := pass{name, rep, rep < *warmups, []record{}}
			paired[name] = map[string]record{}
			supported, unsupported, failed := 0, 0, 0
			cores, responses := []float64{}, []float64{}
			allocated := uint64(0)
			start = time.Now()
			for _, i := range items {
				r := measure(name, i, *deadline)
				p.Records = append(p.Records, r)
				paired[name][i.Query.ID] = r
				allocated += r.Allocated
				if r.Complete {
					supported++
					cores = append(cores, float64(r.CoreNS))
					responses = append(responses, float64(r.ResponseNS))
				} else if r.Unsupported {
					unsupported++
				} else {
					failed++
					success = false
				}
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
			for _, name := range []string{"transfer_patterns", "flash_tb", "tb_complete", "unaccelerated_raptor"} {
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
		comparisons = append(comparisons, map[string]any{"repetition": rep, "warmup": rep < *warmups, "requested": len(items), "assessed": assessed, "unavailable": len(items) - assessed, "equal": equal, "details": details})

	}
	failures := []any{}
	for _, name := range []string{"transfer_patterns", "flash_tb", "tb_complete", "unaccelerated_raptor"} {
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
		for _, name := range []string{"transfer_patterns", "flash_tb", "tb_complete", "unaccelerated_raptor"} {
			ci, e := experiment.ThroughputConfidence(throughput[name], work.Seed)
			if e != nil {
				return e
			}
			ci.Statistic = "supported_queries_per_second_over_all_attempts_makespan"
			intervals[name] = ci
		}
	}
	_, e = experiment.WriteArtifact(filepath.Join(*out, "summary.json"), map[string]any{"success": success, "success_definition": "No mismatched accepted comparison or unexpected query failure; unsupported cases remain unavailable, never counted correct.", "created_utc": time.Now().UTC().Format(time.RFC3339Nano), "provenance": prov, "dataset_sha256": dh, "queries_sha256": qh, "seed": work.Seed, "method": work.Method, "hardware": *hardware, "go_version": runtime.Version(), "goos": runtime.GOOS, "goarch": runtime.GOARCH, "logical_cpus": runtime.NumCPU(), "gomaxprocs": runtime.GOMAXPROCS(0), "input_load_ns": loadNS, "preparation": prep, "configuration": cfg, "query_timeout_ns": deadline.Nanoseconds(), "preparation_timeout_ns": prepDeadline.Nanoseconds(), "repetitions": *reps, "warmups": *warmups, "passes": summaries, "comparisons": comparisons, "throughput_intervals": intervals, "resources_final": experiment.SnapshotResources(), "scope": []string{"Basic Transfer Patterns: full canonical profiles, typed reverse prefix DAGs, direct FIFO-line incidence lookup, time-dependent bicriteria query graph. Fixed maximum4 boardings; no hubs, clusters, A* or heuristic patterns. TP preparation includes its complete shared canonical backend, including one-cell flags, and pattern insertion costs.", "TP and both TB controls use identical destination-specific nonbinding-cap/no-buffer/no-rule/no-accessibility checks. Independent control preprocessing is separately measured. RAPTOR retains all query outcomes independently.", "Core includes capability checks, query graph extraction, direct lookup and full reconstruction. Response adds itinerary validation. Separate loading, partition/preprocessing, index serialization, allocations and whole-process peak RSS.", "Actual all-attempt sequential makespan defines throughput; it is not divided into synthetic query latency. Rotating algorithm order, three repetitions and bootstrap intervals remain shared-host descriptive evidence.", "Public frequency-model diagnostic, not exact Singapore schedules or readiness; regional gate closed."}})
	if e != nil {
		return e
	}
	if !success {
		return fmt.Errorf("mismatch or unexpected query failure; evidence retained")
	}
	return nil
}
func main() {
	if e := run(); e != nil {
		fmt.Fprintln(os.Stderr, e)
		os.Exit(1)
	}
}
