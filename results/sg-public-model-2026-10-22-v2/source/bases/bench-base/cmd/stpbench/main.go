// stpbench retains independent preparation failures for every algorithm/workload.
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

var algorithms = []string{"scalable_transfer_patterns", "transfer_patterns", "flash_tb", "tb_complete", "ordinary_tb", "unaccelerated_raptor"}

func run() error {
	dp := flag.String("dataset", "", "normalized dataset")
	qp := flag.String("queries", "", "frozen queries")
	out := flag.String("out-dir", "", "new directory")
	reps := flag.Int("repetitions", 3, "measured passes")
	warmups := flag.Int("warmups", 1, "retained warmup passes")
	deadline := flag.Duration("timeout", 5*time.Second, "query deadline")
	prepDeadline := flag.Duration("prep-timeout", 180*time.Second, "preparation deadline")
	clusterSize := flag.Int("cluster-size", 32, "maximum cluster size; walking components are indivisible")
	cells := flag.Int("cells", 1, "backend cells; basic TP requires one")
	maxWork := flag.Int("max-work", 200000000, "walking/FLASH backend preparation work budget")
	patternWork := flag.Int("pattern-work", 200000000, "aggregate scalable main+local+long-distance+border insertion work budget; basic TP uses its own counter")
	isolated := flag.Bool("isolate-scalable", false, "prepare only Scalable TP and RAPTOR, to isolate scalability costs")
	hierarchyPath := flag.String("hierarchy", "", "optional dataset-hash-bound explicit trip/hub classification JSON")
	directMode := flag.String("direct-index", "incidence", "direct lookup: incidence, indexed pairs, or bounded demand cache")
	directPairs := flag.Int("max-direct-pairs", 1000000, "eager pair cap, or demand cache keys plus occurrence records")
	borderStorage := flag.String("border-storage", "source", "source prefix DAGs or destination-cluster DAGs")
	clusterDAGs := flag.Int("max-cluster-dags", 100000, "shared cluster DAG count budget")
	borderMode := flag.String("border-mode", "border", "border-only global queue, or expanded ablation")
	localCache := flag.Int("local-cache", 0, "build-only local memo key+result record cap; 0 disables")
	mergeMax := flag.Int("merge-max", 0, "optional border reduction postmerge size cap")
	mergePercent := flag.Int("merge-percent", 0, "minimum percent of merged-cell borders removed")
	disableLocal := flag.Bool("disable-local-sufficiency", false, "ablate certified local-only shortcut")
	maxRuns := flag.Int("max-runs", 10000, "global canonical-run budget")
	hardware := flag.String("hardware", "unrecorded", "verified host description")
	flag.Parse()
	if *isolated {
		algorithms = []string{"scalable_transfer_patterns", "unaccelerated_raptor"}
	}
	comparisonAlgorithms := []string{"scalable_transfer_patterns", "transfer_patterns", "flash_tb", "tb_complete", "unaccelerated_raptor"}
	if *isolated {
		comparisonAlgorithms = append([]string{}, algorithms...)
	}
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
	var hierarchy struct {
		DatasetSHA256     string   `json:"dataset_sha256"`
		LongDistanceTrips []string `json:"long_distance_trips"`
		Hubs              []string `json:"hubs"`
		Provenance        string   `json:"provenance"`
	}
	hierarchyHash := ""
	if *hierarchyPath != "" {
		hierarchyHash, e = read(*hierarchyPath, &hierarchy)
		if e != nil {
			return e
		}
		if hierarchy.DatasetSHA256 != dh || hierarchy.Provenance == "" {
			return fmt.Errorf("hierarchy hash mismatch or missing explicit provenance")
		}
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
	profileCfg := tripbased.FlashConfig{Cells: *cells, MaxBoardings: 4, Limits: tripbased.FlashLimits{MaxStops: 10000, MaxTrips: 100000, MaxClosurePaths: 1000000, MaxWalkSettled: 2000000, MaxTransfers: 500000, MaxRuns: *maxRuns, MaxWork: *maxWork, MaxFlagBytes: 100000000, MaxWitnesses: 1000000, MaxQuerySegments: 1000000}}
	cfg := tripbased.PatternConfig{Profile: profileCfg, MaxPatterns: 1000000, MaxNodes: 2000000, MaxEdges: 3000000, MaxDirectEntries: 5000000, MaxBuildWork: *patternWork, MaxQueryWork: 1000000, MaxQueryLabels: 1000000}
	prep := map[string]any{}
	prepErrors := map[string]error{}
	var before, after runtime.MemStats
	var ctx context.Context
	var cancel context.CancelFunc
	prepare := func(name string, fn func(context.Context) error) {
		runtime.GC()
		runtime.ReadMemStats(&before)
		start = time.Now()
		ctx, cancel = context.WithTimeout(context.Background(), *prepDeadline)
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
	sc := tripbased.ScalableConfig{LongDistanceTrips: hierarchy.LongDistanceTrips, Hubs: hierarchy.Hubs, DirectIndex: *directMode, MaxDirectPairs: *directPairs, BorderStorage: *borderStorage, MaxClusterDAGs: *clusterDAGs, BorderSearchMode: *borderMode, MaxLocalCacheEntries: *localCache, BorderMergeMaxSize: *mergeMax, BorderReductionPercent: *mergePercent, DisableLocalSufficiency: *disableLocal, Patterns: cfg, MaxClusterSize: *clusterSize, MaxDirectArcs: 1000000, MaxProfileRuns: *maxRuns, MaxProfileLabels: 1000000}
	var sx *tripbased.ScalableIndex
	prepare("scalable_transfer_patterns", func(ctx context.Context) error {
		var err error
		sx, err = tripbased.BuildScalable(ctx, d, sc)
		return err
	})
	io, e := experiment.WriteArtifact(filepath.Join(*out, "scalable-index.json"), sx.Snapshot())
	if e != nil {
		return e
	}
	prep["scalable_index_io"] = io
	var x *tripbased.PatternIndex
	var control *tripbased.FlashIndex
	var ordinary *tripbased.Index
	if !*isolated {
		prepare("transfer_patterns", func(ctx context.Context) error {
			var err error
			x, err = tripbased.BuildPatterns(ctx, d, cfg)
			return err
		})
		io, e = experiment.WriteArtifact(filepath.Join(*out, "index.json"), x.Snapshot())
		if e != nil {
			return e
		}
		prep["index_snapshot_io"] = io
		prepare("flash_tb", func(ctx context.Context) error {
			var err error
			control, err = tripbased.BuildFlash(ctx, d, profileCfg)
			return err
		})
		prepErrors["tb_complete"] = prepErrors["flash_tb"]
		prep["tb_complete"] = map[string]any{"shared_preparation": "flash_tb", "implementation": "FlashIndex.SearchBaseline destination-certified complete-transfer control; not ordinary Index.Search"}
		prepare("ordinary_tb", func(ctx context.Context) error {
			var err error
			ordinary, err = tripbased.New(ctx, d, tripbased.Config{StrictLineOrder: true, TransferWalkingLimit: 900, MaxTransfers: 500000, MaxQueuedSegments: 1000000})
			return err
		})
	}
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
		r := record{item: i, Raw: []model.Journey{}, Final: []model.Validated{}}
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
		switch name {
		case "scalable_transfer_patterns":
			result, e := sx.Search(ctx, i.Query)
			err = e
			r.Raw = result.Journeys
			r.Complete = result.Complete
			r.Stats = result.Stats
			r.Graph = result.Graph
		case "ordinary_tb":
			result, e := ordinary.Search(ctx, i.Query)
			err = e
			r.Raw = result.Journeys
			r.Complete = result.Complete
			r.Stats = result.Stats
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
		names := append([]string{}, algorithms...)
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
					if prepErrors[name] == nil {
						success = false
					}
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
	_, e = experiment.WriteArtifact(filepath.Join(*out, "summary.json"), map[string]any{"success": success, "success_definition": "No mismatched accepted comparison or unexpected query failure. Preparation failures and unsupported queries remain unavailable; success does not mean every algorithm was available.", "created_utc": time.Now().UTC().Format(time.RFC3339Nano), "provenance": prov, "dataset_sha256": dh, "queries_sha256": qh, "hierarchy_sha256": hierarchyHash, "hierarchy_provenance": hierarchy.Provenance, "seed": work.Seed, "method": work.Method, "hardware": *hardware, "go_version": runtime.Version(), "goos": runtime.GOOS, "goarch": runtime.GOARCH, "logical_cpus": runtime.NumCPU(), "gomaxprocs": runtime.GOMAXPROCS(0), "input_load_ns": loadNS, "preparation": prep, "isolated_scalable": *isolated, "algorithms": algorithms, "comparison_algorithms": comparisonAlgorithms, "configuration": cfg, "scalable_configuration": sc, "dataset_counts": map[string]int{"stops": len(d.Stops), "trips": len(d.Trips), "connections": len(d.Connections), "footpaths": len(d.Footpaths)}, "query_timeout_ns": deadline.Nanoseconds(), "preparation_timeout_ns": prepDeadline.Nanoseconds(), "repetitions": *reps, "warmups": *warmups, "passes": summaries, "comparisons": comparisons, "throughput_intervals": intervals, "resources_final": experiment.SnapshotResources(), "scope": []string{"Scalable TP v4: optional explicit trip/hub classification, local and long-distance/hub profiles, border-only outer query with hierarchy labels. All-local remains empty-classification case; expanded ablation requires all-local. Optional source/cluster DAGs and incidence/eager-pair/demand lookup. Positive static nonbinding resource profile; not general GTFS/full-paper readiness.", "Every preparation has declared time/work limits; GOMEMLIMIT is a soft whole-process limit, not an enforced per-router memory ceiling. Preparation-unavailable algorithms still retain every query and do not suppress other controls. Pairwise assessed denominators accompany the configured matched intersection.", "tb_complete is FlashIndex.SearchBaseline with its destination-specific certificate. ordinary_tb is Index.Search with its retained global egress guard. They are separate algorithms/capability rows.", "Core includes capability checks, graph extraction, direct lookup and full raw reconstruction; response adds independent validation. Loading/preparation/serialization remain separate. Whole-process RSS is cumulative, not isolated per-router.", "Throughput uses actual all-attempt makespan, never divided-time latency. Three shared-host repetitions and bootstrap intervals are descriptive only.", "Inputs are frozen public frequency-model subsets or explicitly labeled synthetic hierarchy fixtures. Neither proves exact Singapore schedules or physical access. Original and exposed compatibility workloads remain separate; regional gate remains closed."}})
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
