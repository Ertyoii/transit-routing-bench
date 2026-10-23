package main

import (
	"context"
	"flag"
	"fmt"
	"github.com/ertyoii/transit-routing-bench/experiment"
	"github.com/ertyoii/transit-routing-bench/fixtures"
	"github.com/ertyoii/transit-routing-go/comparison"
	"github.com/ertyoii/transit-routing-go/csa"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/presentation"
	"github.com/ertyoii/transit-routing-go/selection"
	"github.com/ertyoii/transit-routing-go/strictjson"
	"github.com/ertyoii/transit-routing-go/validate"
	"os"
	"reflect"
	"runtime"
	"runtime/debug"
	"slices"
	"strconv"
	"strings"
	"time"
)

type queryRecord struct {
	Query      model.Query                 `json:"query"`
	Raw        csa.Result                  `json:"raw"`
	Validated  []model.Validated           `json:"validated"`
	CoreNS     *int64                      `json:"core_ns,omitempty"`
	ResponseNS int64                       `json:"response_ns"`
	ExactTopK  map[int]selection.Result    `json:"exact_top_k"`
	Candidates selection.Result            `json:"candidates"`
	Display    map[int]presentation.Result `json:"display"`
	Errors     []string                    `json:"errors"`
}
type passRecord struct {
	Repetition             int           `json:"repetition"`
	Warmup                 bool          `json:"warmup"`
	Mode                   string        `json:"mode"`
	CoreBatchMakespanNS    int64         `json:"core_batch_makespan_ns"`
	BatchMakespanNS        int64         `json:"batch_makespan_ns"`
	ThroughputQPS          float64       `json:"throughput_qps"`
	SharedConnectionVisits int           `json:"shared_connection_visits"`
	Queries                []queryRecord `json:"queries"`
}

func decodeFile(name string, v any) (string, error) {
	b, e := os.ReadFile(name)
	if e != nil {
		return "", e
	}
	if e = strictjson.Decode(b, v); e != nil {
		return "", e
	}
	return fixtures.Sum(b), nil
}
func run() error {
	fixture := flag.String("fixture", "testdata/tiny.manifest.json", "synthetic manifest when dataset is empty")
	dataset := flag.String("dataset", "", "normalized dataset JSON")
	queryFile := flag.String("queries", "", "query array JSON with explicit walking policies")
	out := flag.String("out", "", "new result JSON")
	reps := flag.Int("repetitions", 3, "measured passes per scheduler")
	warmups := flag.Int("warmups", 1, "retained warmup passes per scheduler")
	kflag := flag.String("k", "1,3,5,10", "common requested/display option counts")
	candidates := flag.Int("candidate-cap", 100, "independent presentation candidate budget")
	labels := flag.Int("max-labels", 100000, "per-query computational label budget")
	journeys := flag.Int("max-journeys", 10000, "per-query raw result budget")
	heuristic := flag.Int("heuristic-labels-per-stop", 0, "explicit non-exact pruning; zero disables")
	penalty := flag.Int64("ranking-transfer-penalty", 300, "ranking only, never changes event time")
	hardware := flag.String("hardware", "unrecorded", "verified host description")
	flag.Parse()
	if *out == "" || *reps < 1 || *reps > 100 || *warmups < 0 || *warmups > 10 || *candidates < 1 {
		return fmt.Errorf("invalid experiment arguments")
	}
	ks := []int{}
	seenK := map[int]bool{}
	for _, s := range strings.Split(*kflag, ",") {
		k, e := strconv.Atoi(s)
		if e != nil || k < 1 || seenK[k] {
			return fmt.Errorf("invalid/duplicate k")
		}
		ks = append(ks, k)
		seenK[k] = true
	}
	var d model.Dataset
	qs := []model.Query{}
	inputHashes := map[string]string{}
	load := time.Now()
	if *dataset == "" {
		b, m, e := fixtures.Load(*fixture)
		if e != nil {
			return e
		}
		d = b.Dataset
		qs = b.Queries
		inputHashes["fixture_data"] = m.DataSHA256
		inputHashes["fixture_license"] = m.LicenseSHA256
	} else {
		if *queryFile == "" {
			return fmt.Errorf("queries required with dataset")
		}
		h, e := decodeFile(*dataset, &d)
		if e != nil {
			return e
		}
		inputHashes["dataset"] = h
		h, e = decodeFile(*queryFile, &qs)
		if e != nil {
			return e
		}
		inputHashes["queries"] = h
	}
	if len(qs) == 0 {
		return fmt.Errorf("empty query set")
	}
	loadNS := time.Since(load).Nanoseconds()
	prep := time.Now()
	idx, e := csa.New(d)
	if e != nil {
		return e
	}
	prepNS := time.Since(prep).Nanoseconds()
	checkerPrep := time.Now()
	checker, e := validate.New(d)
	if e != nil {
		return e
	}
	checkerPrepNS := time.Since(checkerPrep).Nanoseconds()
	config := csa.Config{MaxLabels: *labels, MaxJourneys: *journeys, HeuristicLabelsPerStop: *heuristic}
	resourcesBefore := experiment.SnapshotResources()
	passes := []passRecord{}
	success := true
	equivalenceErrors := []string{}
	validateResult := func(q model.Query, r csa.Result) queryRecord {
		rec := queryRecord{Query: q, Raw: r, Validated: []model.Validated{}, ExactTopK: map[int]selection.Result{}, Display: map[int]presentation.Result{}, Errors: []string{}}
		if _, err := comparison.CheckBinding(checker, q, r); err != nil {
			rec.Errors = append(rec.Errors, err.Error())
			success = false
			return rec
		}
		if r.Error != "" {
			rec.Errors = append(rec.Errors, r.Error)
		}
		for _, j := range r.Journeys {
			v, e := checker.Check(q, j)
			if e != nil {
				rec.Errors = append(rec.Errors, e.Error())
			} else {
				rec.Validated = append(rec.Validated, v)
			}
		}
		// Even incomplete candidates can be shown, but never called exact or unreachable.
		if len(rec.Validated) == len(r.Journeys) {
			rec.Candidates, e = selection.Select(rec.Validated, r.Complete, selection.Spec{Mode: selection.Candidates, CandidateCap: *candidates})
			if e != nil {
				rec.Errors = append(rec.Errors, e.Error())
			}
			for _, k := range ks {
				if r.Complete {
					v, e := selection.Select(rec.Validated, true, selection.Spec{Mode: selection.TopK, K: k})
					if e != nil {
						rec.Errors = append(rec.Errors, e.Error())
					} else {
						rec.ExactTopK[k] = v
					}
				}
				v, e := presentation.Rank(q, rec.Candidates.Journeys, k, *penalty)
				if e != nil {
					rec.Errors = append(rec.Errors, e.Error())
				} else {
					rec.Display[k] = v
				}
			}
		}
		if len(rec.Errors) > 0 {
			success = false
		}
		slices.SortFunc(rec.Validated, selection.Compare)
		return rec
	}
	for rep := 0; rep < *warmups+*reps; rep++ {
		modes := []string{"single", "shared_scan"}
		if rep%2 == 1 {
			slices.Reverse(modes)
		}
		compared := map[string][]queryRecord{}
		for _, mode := range modes {
			pass := passRecord{Repetition: rep, Warmup: rep < *warmups, Mode: mode, Queries: []queryRecord{}}
			batchStart := time.Now()
			if mode == "single" {
				for _, q := range qs {
					start := time.Now()
					core := time.Now()
					r, err := idx.Single(context.Background(), q, config)
					ns := time.Since(core).Nanoseconds()
					pass.CoreBatchMakespanNS += ns
					if err != nil && r.Error == "" {
						r.Error = err.Error()
					}
					record := validateResult(q, r)
					record.CoreNS = &ns
					record.ResponseNS = time.Since(start).Nanoseconds()
					pass.Queries = append(pass.Queries, record)
				}
			} else {
				core := time.Now()
				batch, err := idx.Shared(context.Background(), qs, config)
				pass.CoreBatchMakespanNS = time.Since(core).Nanoseconds()
				pass.SharedConnectionVisits = batch.SharedConnectionVisits
				if err != nil && len(batch.Results) != len(qs) {
					return err
				}
				for i, r := range batch.Results {
					record := validateResult(qs[i], r)
					record.ResponseNS = time.Since(batchStart).Nanoseconds()
					pass.Queries = append(pass.Queries, record)
				}
			}
			pass.BatchMakespanNS = time.Since(batchStart).Nanoseconds()
			completed := 0
			for _, q := range pass.Queries {
				if len(q.Errors) == 0 {
					completed++
				}
			}
			if pass.BatchMakespanNS > 0 {
				pass.ThroughputQPS = float64(completed) * 1e9 / float64(pass.BatchMakespanNS)
			}
			compared[mode] = pass.Queries
			passes = append(passes, pass)
		}
		for i := range qs {
			a, b := compared["single"][i], compared["shared_scan"][i]
			if a.Raw.Complete != b.Raw.Complete || !reflect.DeepEqual(a.Validated, b.Validated) {
				success = false
				equivalenceErrors = append(equivalenceErrors, fmt.Sprintf("rep %d query %s single/shared mismatch", rep, qs[i].ID))
			}
		}
	}
	provenance, e := experiment.Identify(".")
	if e != nil {
		return e
	}
	build := "unavailable"
	if info, ok := debug.ReadBuildInfo(); ok {
		build = info.String()
	}
	intervals := map[string]experiment.Interval{}
	for _, mode := range []string{"single", "shared_scan"} {
		samples := []float64{}
		for _, p := range passes {
			if !p.Warmup && p.Mode == mode {
				samples = append(samples, p.ThroughputQPS)
			}
		}
		if success && len(samples) >= 2 {
			interval, _ := experiment.ThroughputConfidence(samples, 20261017)
			intervals[mode] = interval
		}
	}
	dataKind := d.DataKind
	if *dataset == "" {
		dataKind = "original_synthetic"
	}
	artifact := map[string]any{"resources_before_queries": resourcesBefore, "resources_after_queries": experiment.SnapshotResources(), "throughput_intervals": intervals, "bootstrap_seed": 20261017, "schema_version": model.SchemaVersion, "created_utc": time.Now().UTC().Format(time.RFC3339Nano), "algorithm": "path_enumerating_CSA_extension", "data_kind": dataKind, "input_hashes": inputHashes, "provenance": provenance, "go_version": runtime.Version(), "goos": runtime.GOOS, "goarch": runtime.GOARCH, "gomaxprocs": runtime.GOMAXPROCS(0), "hardware": *hardware, "build_info": build, "input_load_ns": loadNS, "index_preparation_ns": prepNS, "config": config, "k": ks, "candidate_cap": *candidates, "ranking_transfer_penalty_seconds": *penalty, "success": success, "equivalence_errors": equivalenceErrors, "passes": passes, "notes": []string{
		"Correctness-first departure scan with complete path-prefix state; not the paper's optimized single-label EA algorithm and not historical user timings.",
		"Core excludes independent witness validation, final selection and penalty ranking. Single core_batch_makespan is summed query-call time; shared core_batch_makespan is one actual shared call.",
		"Single responses are measured from each sequential call's start; shared responses are from common batch submission through each query's validation/ranking completion. Shared per-query core latency is intentionally absent; never divide makespan by query count as latency.",
		"Batch makespan includes validation/ranking but excludes file loading/index preparation and final JSON serialization. Power, thermals, cache and background load are uncontrolled.",
		"Exact results require complete bounded-universe enumeration. Heuristic discards/budget failures never imply exact top-k or unreachability. Candidate presentation is not generalized-cost optimal search.",
		"Measured/warmup repetitions retained; alternating scheduler order is deterministic. These are smoke/diagnostic runs, not controlled comparative performance claims. Throughput intervals are descriptive percentile bootstraps over repetitions, seed 20261017, 2000 resamples; tiny repetitions do not support comparative performance conclusions. Serialization/writing is separately recorded in the .io.json sidecar; process resource scope is cumulative and not isolated router memory."}}
	artifact["independent_checker_preparation_ns"] = checkerPrepNS
	if _, e = experiment.WriteArtifact(*out, artifact); e != nil {
		return e
	}
	if !success {
		return fmt.Errorf("CSA experiment contains failed queries or equivalence errors; see artifact")
	}
	fmt.Printf("Saved %d scheduler passes for %d queries: %s\n", len(passes), len(qs), *out)
	return nil
}
func main() {
	if e := run(); e != nil {
		fmt.Fprintln(os.Stderr, e)
		os.Exit(1)
	}
}
