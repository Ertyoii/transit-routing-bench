// routebench is a model-relative diagnostic, not a whole-system deployment benchmark.
package main

import (
	"context"
	"flag"
	"fmt"
	"github.com/ertyoii/transit-routing-bench/evaluation"
	"github.com/ertyoii/transit-routing-bench/experiment"
	"github.com/ertyoii/transit-routing-bench/fixtures"
	"github.com/ertyoii/transit-routing-go/csa"
	"github.com/ertyoii/transit-routing-go/eacsa"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/paper"
	"github.com/ertyoii/transit-routing-go/presentation"
	"github.com/ertyoii/transit-routing-go/raptor"
	"github.com/ertyoii/transit-routing-go/selection"
	"github.com/ertyoii/transit-routing-go/strictjson"
	"github.com/ertyoii/transit-routing-go/validate"
	"math/rand/v2"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"slices"
	"strconv"
	"strings"
	"time"
)

type WorkItem struct {
	Stratum string      `json:"stratum"`
	Query   model.Query `json:"query"`
}
type Workload struct {
	Seed          uint64     `json:"seed"`
	Method        string     `json:"method"`
	DatasetSHA256 string     `json:"dataset_sha256"`
	Items         []WorkItem `json:"items"`
}
type Presentation struct {
	CandidateCap int                 `json:"candidate_cap"`
	K            int                 `json:"k"`
	Candidates   selection.Result    `json:"candidates"`
	Display      presentation.Result `json:"display"`
	Quality      *evaluation.Quality `json:"quality,omitempty"`
}
type Record struct {
	WorkItem
	Raw                []model.Journey   `json:"raw"`
	Validated          []model.Validated `json:"validated"`
	Complete           bool              `json:"complete"`
	Stats              any               `json:"stats"`
	Error              string            `json:"error,omitempty"`
	TimedOut           bool              `json:"timed_out"`
	CoreNS             *int64            `json:"core_ns,omitempty"`
	ResponseNS         int64             `json:"response_ns"`
	Final              []Presentation    `json:"final"`
	ReferenceAvailable bool              `json:"reference_available"`
	TopK               int               `json:"top_k,omitempty"`
	TopKComplete       bool              `json:"top_k_complete"`
	CapComplete        bool              `json:"all_boarding_caps_complete"`
	CapResults         []csa.CapResult   `json:"cap_results,omitempty"`
}
type Pass struct {
	Algorithm  string   `json:"algorithm"`
	Cap        int      `json:"heuristic_labels_per_stop"`
	Repetition int      `json:"repetition"`
	Warmup     bool     `json:"warmup"`
	Batches    []Batch  `json:"batches"`
	Records    []Record `json:"records"`
}
type Batch struct {
	Size               int     `json:"size"`
	CoreNS             int64   `json:"core_makespan_ns"`
	ResponseNS         int64   `json:"response_makespan_ns"`
	Successes          int     `json:"successful_queries"`
	Throughput         float64 `json:"successful_throughput_qps"`
	Visits             int     `json:"shared_connection_visits,omitempty"`
	CoreAllocatedBytes uint64  `json:"core_allocated_bytes,omitempty"`
}
type Summary struct {
	File               string                  `json:"file"`
	SHA256             string                  `json:"sha256"`
	Algorithm          string                  `json:"algorithm"`
	Cap                int                     `json:"heuristic_labels_per_stop"`
	Repetition         int                     `json:"repetition"`
	Warmup             bool                    `json:"warmup"`
	Queries            int                     `json:"queries"`
	Errors             int                     `json:"errors"`
	Timeouts           int                     `json:"timeouts"`
	Incomplete         int                     `json:"incomplete"`
	Core               evaluation.Distribution `json:"query_core_ns"`
	Response           evaluation.Distribution `json:"query_response_ns"`
	Makespan           int64                   `json:"total_response_makespan_ns"`
	Throughput         float64                 `json:"successful_throughput_qps"`
	CoreAllocatedBytes uint64                  `json:"core_allocated_bytes,omitempty"`
}

func read(path string, v any) (string, error) {
	b, e := os.ReadFile(path)
	if e != nil {
		return "", e
	}
	if e = strictjson.Decode(b, v); e != nil {
		return "", e
	}
	return fixtures.Sum(b), nil
}
func numbers(s string, allowZero bool) ([]int, error) {
	ns := []int{}
	seen := map[int]bool{}
	for _, word := range strings.Split(s, ",") {
		n, e := strconv.Atoi(word)
		if e != nil || n < 0 || n == 0 && !allowZero || seen[n] {
			return nil, fmt.Errorf("invalid integers %q", s)
		}
		seen[n] = true
		ns = append(ns, n)
	}
	return ns, nil
}
func objectives(q model.Query, vs []model.Validated) []int64 {
	out := make([]int64, q.MaxBoardings+1)
	for i := range out {
		out[i] = paper.Infinity
	}
	for _, v := range vs {
		for b := v.Metrics.Boardings; b < len(out); b++ {
			out[b] = min(out[b], v.Metrics.Arrival)
		}
	}
	return out
}
func run() error {
	dataset := flag.String("dataset", "", "normalized model JSON")
	queries := flag.String("queries", "", "frozen stratified workload JSON")
	out := flag.String("out-dir", "", "new artifact directory")
	capsFlag := flag.String("caps", "8,32,128", "heuristic per-stop caps, 0 disables")
	candidateFlag := flag.String("candidate-caps", "10,100", "independent presentation budgets")
	kFlag := flag.String("k", "1,3,5,10", "display sizes")
	reps := flag.Int("repetitions", 3, "measured repetitions")
	warmups := flag.Int("warmups", 1, "retained warmups")
	batchSize := flag.Int("batch-size", 8, "shared batch size")
	timeout := flag.Duration("timeout", 5*time.Second, "single-call OR whole-shared-batch core deadline")
	maxLabels := flag.Int("max-labels", 100000, "per-query computational labels")
	maxJourneys := flag.Int("max-journeys", 10000, "per-query raw results")
	hardware := flag.String("hardware", "unrecorded", "verified machine description")
	exactK := flag.Int("exact-k", 0, "certified global top-k scan; requires caps=0")
	stratified := flag.Bool("stratified", false, "union exact-k at each boarding cap; per-cap label budget, common call deadline")
	reserve := flag.Bool("reserve-pareto", false, "reserve raw arrival/boarding representatives in candidate budget")
	flag.Parse()
	if *dataset == "" || *queries == "" || *out == "" || *reps < 1 || *warmups < 0 || *batchSize < 1 || *timeout <= 0 {
		return fmt.Errorf("invalid required arguments")
	}
	caps, e := numbers(*capsFlag, true)
	if e != nil {
		return e
	}
	if *exactK < 0 || *stratified && *exactK == 0 {
		return fmt.Errorf("invalid exact/stratified configuration")
	}
	if *exactK > 0 {
		for _, cap := range caps {
			if cap != 0 {
				return fmt.Errorf("exact-k requires heuristic caps=0")
			}
		}
	}
	candidateCaps, e := numbers(*candidateFlag, false)
	if e != nil {
		return e
	}
	ks, e := numbers(*kFlag, false)
	if e != nil {
		return e
	}
	if e = os.Mkdir(*out, 0700); e != nil {
		return e
	}
	start := time.Now()
	var d model.Dataset
	var work Workload
	dataHash, e := read(*dataset, &d)
	if e != nil {
		return e
	}
	queryHash, e := read(*queries, &work)
	if e != nil {
		return e
	}
	if work.DatasetSHA256 != dataHash || len(work.Items) == 0 {
		return fmt.Errorf("workload input hash mismatch or empty workload")
	}
	loadNS := time.Since(start).Nanoseconds()
	ids := map[string]bool{}
	for _, item := range work.Items {
		if ids[item.Query.ID] || item.Stratum == "" {
			return fmt.Errorf("duplicate query ID or absent stratum")
		}
		ids[item.Query.ID] = true
		if e = item.Query.Validate(d); e != nil {
			return e
		}
	}
	before := experiment.SnapshotResources()
	prep := map[string]int64{}
	start = time.Now()
	ea, e := eacsa.New(d)
	if e != nil {
		return e
	}
	prep["ea_csa"] = time.Since(start).Nanoseconds()
	start = time.Now()
	rap, e := raptor.New(d)
	if e != nil {
		return e
	}
	prep["raptor"] = time.Since(start).Nanoseconds()
	start = time.Now()
	cand, e := csa.New(d)
	if e != nil {
		return e
	}
	prep["candidate_csa"] = time.Since(start).Nanoseconds()
	start = time.Now()
	checker, e := validate.New(d)
	if e != nil {
		return e
	}
	prep["independent_checker"] = time.Since(start).Nanoseconds()
	afterPrep := experiment.SnapshotResources()
	provenance, e := experiment.Identify(".")
	if e != nil {
		return e
	}
	references := map[string][]model.Validated{}
	referenceValid := map[string]bool{}
	summaries := []Summary{}
	fatalErrors := []string{}
	success := true
	check := func(item WorkItem, js []model.Journey, complete bool, stats any, errText string) Record {
		r := Record{WorkItem: item, Raw: js, Validated: []model.Validated{}, Complete: complete, Stats: stats, Error: errText, Final: []Presentation{}}
		r.TimedOut = strings.Contains(errText, context.DeadlineExceeded.Error())
		for _, j := range js {
			v, e := checker.Check(item.Query, j)
			if e != nil {
				r.Error += "; invalid witness: " + e.Error()
			} else {
				r.Validated = append(r.Validated, v)
			}
		}
		slices.SortFunc(r.Validated, selection.Compare)
		return r
	}
	finish := func(r *Record) {
		r.ReferenceAvailable = referenceValid[r.Query.ID]
		if len(r.Raw) != len(r.Validated) {
			return
		}
		for _, budget := range candidateCaps {
			c, e := selection.Select(r.Validated, r.Complete, selection.Spec{Mode: selection.Candidates, CandidateCap: budget})
			if *reserve {
				c, e = selection.ReserveArrivalBoarding(r.Validated, budget)
			}
			if e != nil {
				r.Error += "; " + e.Error()
				continue
			}
			for _, k := range ks {
				display, e := presentation.Rank(r.Query, c.Journeys, k, 300)
				if e != nil {
					r.Error += "; " + e.Error()
					continue
				}
				f := Presentation{CandidateCap: budget, K: k, Candidates: c, Display: display}
				if referenceValid[r.Query.ID] {
					shown := []model.Validated{}
					for _, o := range display.Options {
						shown = append(shown, o.Journey)
					}
					q, e := evaluation.Compare(r.Query, references[r.Query.ID], r.Validated, c.Journeys, shown, 300)
					if e != nil {
						r.Error += "; reference counterexample: " + e.Error()
					} else {
						f.Quality = &q
					}
				}
				r.Final = append(r.Final, f)
			}
		}
	}
	save := func(p Pass) error {
		s := Summary{Algorithm: p.Algorithm, Cap: p.Cap, Repetition: p.Repetition, Warmup: p.Warmup, Queries: len(p.Records)}
		core, response := []float64{}, []float64{}
		for _, r := range p.Records {
			if r.Error != "" {
				s.Errors++
			}
			if r.TimedOut {
				s.Timeouts++
			}
			if !r.Complete {
				s.Incomplete++
			}
			if r.CoreNS != nil {
				core = append(core, float64(*r.CoreNS))
			}
			response = append(response, float64(r.ResponseNS))
		}
		s.Core = evaluation.Summarize(core)
		s.Response = evaluation.Summarize(response)
		for _, b := range p.Batches {
			s.Makespan += b.ResponseNS
			s.CoreAllocatedBytes += b.CoreAllocatedBytes
		}
		if s.Makespan > 0 {
			s.Throughput = float64(s.Queries-s.Errors) * 1e9 / float64(s.Makespan)
		}
		s.File = fmt.Sprintf("%02d-%s-cap%d.json", p.Repetition, p.Algorithm, p.Cap)
		io, e := experiment.WriteArtifact(filepath.Join(*out, s.File), p)
		if e != nil {
			return e
		}
		s.SHA256 = io.SHA256
		summaries = append(summaries, s)
		if s.Errors > 0 {
			success = false
		}
		fmt.Printf("%s rep=%d queries=%d errors=%d timeouts=%d incomplete=%d response p50=%.2fms p95=%.2fms\n", p.Algorithm, p.Repetition, s.Queries, s.Errors, s.Timeouts, s.Incomplete, s.Response.P50/1e6, s.Response.P95/1e6)
		return nil
	}
	for rep := 0; rep < *warmups+*reps; rep++ {
		items := append([]WorkItem{}, work.Items...)
		rng := rand.New(rand.NewPCG(work.Seed, uint64(rep)))
		rng.Shuffle(len(items), func(i, j int) { items[i], items[j] = items[j], items[i] })
		// Paired paper reference checks precede candidates, whose comparisons need a
		// complete validated reference. Kernel order alternates after the first pass.
		algorithms := []string{"ea_csa", "raptor"}
		if rep%2 == 1 {
			slices.Reverse(algorithms)
		}
		paired := map[string]map[string]Record{}
		for _, name := range algorithms {
			p := Pass{Algorithm: name, Repetition: rep, Warmup: rep < *warmups, Records: []Record{}, Batches: []Batch{}}
			paired[name] = map[string]Record{}
			for _, item := range items {
				batchStart := time.Now()
				ctx, cancel := context.WithTimeout(context.Background(), *timeout)
				coreStart := time.Now()
				var result paper.Result
				var err error
				if name == "ea_csa" {
					result, err = ea.Search(ctx, item.Query)
				} else {
					result, err = rap.Search(ctx, item.Query)
				}
				ns := time.Since(coreStart).Nanoseconds()
				cancel()
				// Context cancellation is cooperative; a timer may be delivered late
				// on one busy worker. A returned result past the measured deadline
				// is retained as partial evidence, never counted as on-time success.
				if ns > timeout.Nanoseconds() {
					result.Complete = false
					if !strings.Contains(result.Error, context.DeadlineExceeded.Error()) {
						result.Error += context.DeadlineExceeded.Error() + " (measured core deadline overrun)"
					}
				}
				if err != nil && result.Error == "" {
					result.Error = err.Error()
				}
				r := check(item, result.Journeys, result.Complete, result.Stats, result.Error)
				r.CoreNS = &ns
				paired[name][r.Query.ID] = r
				r.ResponseNS = time.Since(batchStart).Nanoseconds()
				p.Records = append(p.Records, r)
				b := Batch{Size: 1, CoreNS: ns, ResponseNS: r.ResponseNS}
				if r.Error == "" {
					b.Successes = 1
					b.Throughput = 1e9 / float64(b.ResponseNS)
				}
				p.Batches = append(p.Batches, b)
			}
			if e = save(p); e != nil {
				return e
			}
		}
		for _, item := range items {
			a, b := paired["ea_csa"][item.Query.ID], paired["raptor"][item.Query.ID]
			valid := a.Error == "" && b.Error == "" && a.Complete && b.Complete && reflect.DeepEqual(objectives(item.Query, a.Validated), objectives(item.Query, b.Validated))
			if !valid {
				success = false
				fatalErrors = append(fatalErrors, fmt.Sprintf("rep %d query %s: exact references incomplete or disagree", rep, item.Query.ID))
				referenceValid[item.Query.ID] = false
				continue
			}
			if rep > 0 && referenceValid[item.Query.ID] && !reflect.DeepEqual(objectives(item.Query, references[item.Query.ID]), objectives(item.Query, b.Validated)) {
				success = false
				fatalErrors = append(fatalErrors, "reference changed with repetition/order: "+item.Query.ID)
				referenceValid[item.Query.ID] = false
				continue
			}
			references[item.Query.ID] = b.Validated
			referenceValid[item.Query.ID] = true
		}
		for _, cap := range caps {
			cfg := csa.Config{MaxLabels: *maxLabels, MaxJourneys: *maxJourneys, HeuristicLabelsPerStop: cap, ExactTopK: *exactK}
			singleSearch, sharedSearch := cand.Single, cand.Shared
			if *stratified {
				singleSearch = cand.StratifiedSingle
				sharedSearch = cand.StratifiedShared
			}
			modes := []string{"candidate_single", "candidate_shared"}
			if rep%2 == 1 {
				slices.Reverse(modes)
			}
			matched := map[string]map[string]Record{}
			for _, name := range modes {
				algorithm := name
				if *exactK > 0 {
					kind := "exact"
					if *stratified {
						kind = "stratified"
					}
					algorithm = fmt.Sprintf("candidate_%s%d_%s", kind, *exactK, strings.TrimPrefix(name, "candidate_"))
				}
				p := Pass{Algorithm: algorithm, Cap: cap, Repetition: rep, Warmup: rep < *warmups, Records: []Record{}, Batches: []Batch{}}
				matched[name] = map[string]Record{}
				size := 1
				if name == "candidate_shared" {
					size = *batchSize
				}
				for from := 0; from < len(items); from += size {
					to := min(from+size, len(items))
					var memoryBefore, memoryAfter runtime.MemStats
					runtime.ReadMemStats(&memoryBefore)
					batchStart := time.Now()
					ctx, cancel := context.WithTimeout(context.Background(), *timeout)
					coreStart := time.Now()
					results := []csa.Result{}
					visits := 0
					if name == "candidate_single" {
						r, err := singleSearch(ctx, items[from].Query, cfg)
						if err != nil && r.Error == "" {
							r.Error = err.Error()
						}
						results = append(results, r)
					} else {
						qs := []model.Query{}
						for _, item := range items[from:to] {
							qs = append(qs, item.Query)
						}
						b, err := sharedSearch(ctx, qs, cfg)
						results = b.Results
						visits = b.SharedConnectionVisits
						if len(results) != len(qs) {
							cancel()
							return fmt.Errorf("shared result cardinality: %v", err)
						}
					}
					ns := time.Since(coreStart).Nanoseconds()
					runtime.ReadMemStats(&memoryAfter)
					cancel()
					if ns > timeout.Nanoseconds() {
						for i := range results {
							results[i].Complete = false
							results[i].TopKComplete = false
							results[i].CapComplete = false
							if !strings.Contains(results[i].Error, context.DeadlineExceeded.Error()) {
								results[i].Error += context.DeadlineExceeded.Error() + " (measured core deadline overrun)"
							}
						}
					}
					batch := Batch{Size: to - from, CoreNS: ns, Visits: visits, CoreAllocatedBytes: memoryAfter.TotalAlloc - memoryBefore.TotalAlloc}
					for i, result := range results {
						r := check(items[from+i], result.Journeys, result.Complete, result.Stats, result.Error)
						r.TopK = result.TopK
						r.TopKComplete = result.TopKComplete
						r.CapComplete = result.CapComplete
						r.CapResults = result.CapResults
						if name == "candidate_single" {
							v := ns
							r.CoreNS = &v
						}
						finish(&r)
						r.ResponseNS = time.Since(batchStart).Nanoseconds()
						if r.Error == "" {
							batch.Successes++
						}
						p.Records = append(p.Records, r)
						matched[name][r.Query.ID] = r
					}
					batch.ResponseNS = time.Since(batchStart).Nanoseconds()
					batch.Throughput = float64(batch.Successes) * 1e9 / float64(batch.ResponseNS)
					p.Batches = append(p.Batches, batch)
				}
				if e = save(p); e != nil {
					return e
				}
			}
			for _, item := range items {
				a, b := matched["candidate_single"][item.Query.ID], matched["candidate_shared"][item.Query.ID]
				if a.Error == "" && b.Error == "" && (a.Complete != b.Complete || a.TopKComplete != b.TopKComplete || a.CapComplete != b.CapComplete || !reflect.DeepEqual(a.Validated, b.Validated)) {
					success = false
					fatalErrors = append(fatalErrors, fmt.Sprintf("rep %d cap %d single/shared mismatch: %s", rep, cap, item.Query.ID))
				}
			}
		}
	}
	intervals := map[string]experiment.Interval{}
	samples := map[string][]float64{}
	for _, s := range summaries {
		if !s.Warmup {
			key := fmt.Sprintf("%s-cap%d", s.Algorithm, s.Cap)
			samples[key] = append(samples[key], s.Throughput)
		}
	}
	for k, values := range samples {
		if len(values) >= 2 {
			v, e := experiment.ThroughputConfidence(values, work.Seed)
			if e != nil {
				return e
			}
			intervals[k] = v
		}
	}
	manifest := map[string]any{"success": success, "errors": fatalErrors, "created_utc": time.Now().UTC().Format(time.RFC3339Nano), "dataset_sha256": dataHash, "workload_sha256": queryHash, "data_kind": d.DataKind, "workload": work, "provenance": provenance, "go_version": runtime.Version(), "goos": runtime.GOOS, "goarch": runtime.GOARCH, "gomaxprocs": runtime.GOMAXPROCS(0), "hardware": *hardware, "input_load_ns": loadNS, "preparation_ns": prep, "resources_before_preparation": before, "resources_after_preparation": afterPrep, "resources_after_queries": experiment.SnapshotResources(), "paper_capability": ea.Capabilities(), "raptor_preparation": rap.Preparation(), "batch_size": *batchSize, "timeout_ns": timeout.Nanoseconds(), "max_labels": *maxLabels, "max_journeys": *maxJourneys, "heuristic_caps": caps, "candidate_caps": candidateCaps, "k": ks, "ranking_transfer_penalty_seconds": 300, "warmups": *warmups, "repetitions": *reps, "summaries": summaries, "throughput_intervals": intervals, "reference_valid": referenceValid, "notes": []string{
		"EA-CSA uses boarding layers of basic Figure 3 CSA; RAPTOR uses route rounds with overtaking splits. Both implement declared role-walking/static-stop-pair extensions and return Pareto representatives, not all identities or strict top-k.",
		"Reference vectors are cross-implementation agreement, not independent full-network optimality proof; tiny oracle evidence is separate. Shared walking preprocessing and production transfer resolver are a common-mode risk.",
		"Candidate raw completeness means full bounded graph-walk enumeration only. Heuristic discards and computational exhaustion never establish unreachability or exact top-k. Quality of partial outputs is retained, with errors/timeouts in denominators.",
		"Core excludes validation, presentation and serialization. Response includes validation/presentation, excludes loading, preparation and artifact IO; shared response begins at common batch submission, never makespan divided by size. Paper response includes validation only; candidate presentation work is separately attributable in raw records and not equivalent work.",
		"Deadline applies to a single core call or entire shared core batch, not per shared lane. Context cancellation is cooperative, with a measured wall-time overrun check after return; no hard preemption is claimed. P50/P95 include observed timeout durations, not substituted successful-query latency. Serialization and file IO have per-pass sidecars.",
		"All warmups/raw/final results retained; seeded per-repetition query permutations and alternating mode order. Throughput confidence intervals use repetitions as resampling unit, 2000 percentile bootstrap draws; 3 measured repetitions and a stratified convenience workload do not support general performance or speedup claims.",
		"Process RSS/CPU are cumulative over all indices and passes, not isolated router costs. Heap snapshots and preprocessing costs are separately retained. Walking semantics depend on the pinned dataset and its audit; no verified pedestrian access or travel time is implied.",
		"Arrival gaps are per transfer cap. Ranking regret uses duration + 300 seconds/transfer without changing schedule time. Raw, earliest-arrival candidate budget and displayed set are distinguished; missing results are never zero gaps.",
	}}
	manifest["exact_k"] = *exactK
	manifest["stratified_boarding_caps"] = *stratified
	manifest["reserve_pareto_candidates"] = *reserve
	manifest["candidate_memory_scope"] = "Core allocated-byte counter deltas include query context/adapter setup and returned raw outputs, exclude validation/ranking and index preparation; shared measurements are whole-batch totals, not isolated per-query peaks. ReadMemStats itself is outside core_ns but in response_ns."
	manifest["stratified_budget_scope"] = "Each boarding-cap lane receives max_labels independently; up to (MaxBoardings+1)*max_labels per request, with a common single-call or whole-batch wall deadline. The union is candidate presentation, not a global strict-top-k list."
	if _, e = experiment.WriteArtifact(filepath.Join(*out, "manifest.json"), manifest); e != nil {
		return e
	}
	if !success {
		return fmt.Errorf("diagnostic contains failed queries or comparisons; full evidence retained")
	}
	return nil
}
func main() {
	if e := run(); e != nil {
		fmt.Fprintln(os.Stderr, e)
		os.Exit(1)
	}
}
