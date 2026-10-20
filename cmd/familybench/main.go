package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"github.com/ertyoii/transit-routing-bench/evaluation"
	"github.com/ertyoii/transit-routing-bench/experiment"
	"github.com/ertyoii/transit-routing-bench/fixtures"
	"github.com/ertyoii/transit-routing-go/comparison"
	"github.com/ertyoii/transit-routing-go/csa"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/presentation"
	"github.com/ertyoii/transit-routing-go/recommend"
	"github.com/ertyoii/transit-routing-go/strictjson"
	"github.com/ertyoii/transit-routing-go/validate"
	"math/rand/v2"
	"os"
	"path/filepath"
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
type contracts struct {
	Walking         bool `json:"arrival_boardings_walking"`
	EA              bool `json:"earliest_arrival"`
	Pareto          bool `json:"arrival_boardings"`
	Score           bool `json:"best_score"`
	ArrivalK        bool `json:"arrival_top_k"`
	ScoreK          bool `json:"score_top_k"`
	ArrivalThroughK int  `json:"arrival_certified_through_k"`
	ScoreThroughK   int  `json:"score_certified_through_k"`
}
type record struct {
	Quality   *recommend.Result `json:"recommendation_quality,omitempty"`
	QualityNS int64             `json:"quality_ns"`
	item
	Raw              []model.Journey             `json:"raw"`
	Final            []model.Validated           `json:"final"`
	Display          map[int]presentation.Result `json:"display_options"`
	Completed        bool                        `json:"completed"`
	Attempted        bool                        `json:"attempted"`
	ValidEmpty       bool                        `json:"valid_empty"`
	Transit          bool                        `json:"transit"`
	Status           string                      `json:"status"`
	Error            string                      `json:"error,omitempty"`
	Certificates     contracts                   `json:"certificates"`
	Detail           any                         `json:"detail"`
	Batch            int                         `json:"batch"`
	CoreNS           *int64                      `json:"core_ns"`
	ServiceStart     int64                       `json:"service_start_offset_ns"`
	SearchDone       int64                       `json:"search_done_offset_ns"`
	ValidationStart  int64                       `json:"validation_start_offset_ns"`
	ResponseNS       int64                       `json:"response_ns"`
	ValidationRankNS int64                       `json:"validation_rank_ns"`
}
type batchRecord struct {
	ID         int                  `json:"id"`
	QueryIDs   []string             `json:"query_ids"`
	Shared     bool                 `json:"shared_search"`
	CoreNS     int64                `json:"core_ns"`
	MakespanNS int64                `json:"makespan_ns"`
	Allocated  uint64               `json:"allocated_bytes"`
	Detail     any                  `json:"detail"`
	Resources  experiment.Resources `json:"resources"`
}
type pass struct {
	Algorithm  string        `json:"algorithm"`
	Repetition int           `json:"repetition"`
	Warmup     bool          `json:"warmup"`
	Records    []record      `json:"records"`
	Batches    []batchRecord `json:"batches"`
}

func read(path string, v any) (string, error) {
	b, e := os.ReadFile(path)
	if e != nil {
		return "", e
	}
	return fixtures.Sum(b), strictjson.Decode(b, v)
}
func status(e error) string {
	if e == nil {
		return "complete"
	}
	var classified *outcomeError
	if errors.As(e, &classified) {
		return classified.outcome
	}
	s := e.Error()
	switch {
	case strings.Contains(s, "capability:"):
		return "unsupported_semantics"
	case strings.Contains(s, "deadline") || strings.Contains(s, "canceled"):
		return "deadline"
	case strings.Contains(s, "selection budget"):
		return "selection_budget"
	case strings.Contains(s, "labels budget") || strings.Contains(s, "label budget"):
		return "internal_label_limit"
	case strings.Contains(s, "work budget"):
		return "internal_work_limit"
	case strings.Contains(s, "budget") || strings.Contains(s, "limit"):
		return "internal_index_limit"
	default:
		return "routing_error"
	}
}
func run() error {
	dp := flag.String("dataset", "", "normalized data")
	fixture := flag.String("fixture", "", "pinned original-synthetic manifest; alternative to dataset and queries")
	scopedPath := flag.String("scoped-config", "", "explicit configuration JSON required for scoped adapters")
	qp := flag.String("queries", "", "frozen queries")
	out := flag.String("out-dir", "", "new output")
	alg := flag.String("algorithm", "", "one isolated router: "+strings.Join(append(append([]string{}, names...), scopedNames...), ", "))
	k := flag.Int("candidate-k", 10, "internal exact arrival k / per cap k")
	size := flag.Int("batch-size", 8, "common submission size")
	reps := flag.Int("repetitions", 3, "measured repetitions")
	warm := flag.Int("warmups", 1, "retained warmups")
	deadline := flag.Duration("batch-timeout", 5*time.Second, "common submission deadline, including queue and postprocessing")
	prepTimeout := flag.Duration("prep-timeout", 30*time.Second, "cooperative preparation deadline")
	labels := flag.Int("max-labels", 100000, "CSA per lane labels; cap-union expands per OD")
	transfers := flag.Int("max-transfers", 5000000, "development index safety cap, not physical memory")
	workLimit := flag.Int("max-work", 2000000000, "development algorithm work guard")
	witnesses := flag.Int("max-witnesses", 2000000, "development retained preprocessing witness guard")
	rssStop := flag.Int64("rss-safety-stop", 12000000000, "sampled development peakRSS stop; not hard memory confinement")
	quality := flag.Bool("quality", false, "measure validated candidates and pattern_anchors_v1 selection; included in response time")
	preferencesPath := flag.String("preference-scenarios", "", "explicit finite choice scenarios; requires quality; measured within response")
	flag.Parse()
	var choiceConfig *recommend.ChoiceConfig
	preferenceSHA := ""
	if *preferencesPath != "" {
		if !*quality {
			return fmt.Errorf("preferences require quality")
		}
		var cfg recommend.ChoiceConfig
		var err error
		preferenceSHA, err = read(*preferencesPath, &cfg)
		if err != nil {
			return err
		}
		if err = cfg.Validate(); err != nil {
			return err
		}
		choiceConfig = &cfg
	}
	if (*fixture == "" && (*dp == "" || *qp == "")) || (*fixture != "" && (*dp != "" || *qp != "")) || *out == "" || *alg == "" || *k < 1 || *size < 1 || *reps < 1 || *warm < 0 || *deadline <= 0 || *prepTimeout <= 0 || *rssStop <= 0 || *witnesses <= 0 {
		return fmt.Errorf("invalid flags")
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
	// Cooperative monitoring plus abrupt exit protects the desktop if a native
	// preparation does not observe cancellation. Sampling can overshoot the guard.
	stop := make(chan struct{})
	defer close(stop)
	go func() {
		tick := time.NewTicker(100 * time.Millisecond)
		defer tick.Stop()
		for {
			select {
			case <-stop:
				return
			case <-tick.C:
				r := experiment.SnapshotResources()
				if r.Process.Available && r.Process.MaxRSSBytes > *rssStop {
					b, _ := json.Marshal(map[string]any{"status": "observed_rss_safety_stop", "threshold_bytes": *rssStop, "resources": r, "scope": "sampled development safeguard; not hard confinement or OOM"})
					_ = os.WriteFile(filepath.Join(*out, "resource-stop.json"), b, 0600)
					os.Exit(88)
				}
			}
		}
	}()
	var d model.Dataset
	var w workload
	t := time.Now()
	var dh, qh, fixtureSHA string
	if *fixture != "" {
		bundle, manifest, err := fixtures.Load(*fixture)
		if err != nil {
			return err
		}
		d = bundle.Dataset
		data, err := json.Marshal(d)
		if err != nil {
			return err
		}
		dh = fixtures.Sum(data)
		w = workload{Seed: uint64(manifest.Seed), Method: manifest.Generator, DatasetSHA256: dh}
		for _, q := range bundle.Queries {
			w.Items = append(w.Items, item{Stratum: "original_synthetic", Query: q})
		}
		queries, err := json.Marshal(w)
		if err != nil {
			return err
		}
		qh = fixtures.Sum(queries)
		manifestBytes, err := os.ReadFile(*fixture)
		if err != nil {
			return err
		}
		fixtureSHA = fixtures.Sum(manifestBytes)
	} else {
		dh, e = read(*dp, &d)
		if e != nil {
			return e
		}
		qh, e = read(*qp, &w)
		if e != nil {
			return e
		}
	}
	loadNS := time.Since(t).Nanoseconds()
	if dh != w.DatasetSHA256 || len(w.Items) == 0 {
		return fmt.Errorf("input binding")
	}
	if e = d.Validate(); e != nil {
		return e
	}
	ids := map[string]bool{}
	for _, i := range w.Items {
		if ids[i.Query.ID] {
			return fmt.Errorf("duplicate query")
		}
		ids[i.Query.ID] = true
		if e = i.Query.Validate(d); e != nil {
			return e
		}
	}
	var scoped scopedConfig
	scopedSHA := ""
	if isScoped(*alg) {
		if *scopedPath == "" {
			return fmt.Errorf("scoped adapter requires -scoped-config")
		}
		scopedSHA, e = read(*scopedPath, &scoped)
		if e != nil {
			return e
		}
	} else if *scopedPath != "" {
		return fmt.Errorf("scoped configuration supplied for a legacy adapter")
	}
	runtime.GC()
	var before, after runtime.MemStats
	runtime.ReadMemStats(&before)
	t = time.Now()
	ctx, cancel := context.WithTimeout(context.Background(), *prepTimeout)
	var r *router
	var prepErr error
	if isScoped(*alg) {
		r, prepErr = prepareScoped(ctx, d, *alg, scoped)
	} else {
		r, prepErr = prepare(ctx, d, *alg, *k, *labels, *transfers, *workLimit, *witnesses)
	}
	prepNS := time.Since(t).Nanoseconds()
	if prepErr == nil && (ctx.Err() != nil || prepNS > prepTimeout.Nanoseconds()) {
		prepErr = fmt.Errorf("preparation deadline exceeded")
	}
	cancel()
	runtime.ReadMemStats(&after)
	prep := map[string]any{"elapsed_ns": prepNS, "allocated_bytes": after.TotalAlloc - before.TotalAlloc, "complete": prepErr == nil, "status": status(prepErr), "error": fmt.Sprint(prepErr), "resources": experiment.SnapshotResources()}
	if r.cost != nil {
		prep["index_cost_summary"] = r.cost()
	}
	runtime.ReadMemStats(&before)
	t = time.Now()
	checker, e := validate.New(d)
	if e != nil {
		return e
	}
	checkerNS := time.Since(t).Nanoseconds()
	runtime.ReadMemStats(&after)
	checkPrep := map[string]any{"elapsed_ns": checkerNS, "allocated_bytes": after.TotalAlloc - before.TotalAlloc, "resources": experiment.SnapshotResources()}
	runtime.ReadMemStats(&before)
	qualityPrepStart := time.Now()
	var qualityIndex *recommend.Index
	if *quality {
		qualityIndex, e = recommend.New(d)
		if e != nil {
			return e
		}
	}
	qualityPrepNS := time.Since(qualityPrepStart).Nanoseconds()
	runtime.ReadMemStats(&after)
	qualityPrep := map[string]any{"elapsed_ns": qualityPrepNS, "allocated_bytes": after.TotalAlloc - before.TotalAlloc, "resources": experiment.SnapshotResources()}
	fmt.Println(*alg, "preparation", prepNS, "ns", prepErr)
	summaries := []any{}
	qps := []float64{}
	fatal := false
	finalize := func(i item, raw rawResult, sub time.Time, b int, core *int64, start, done int64, ctx context.Context, limit time.Duration) record {
		z := record{item: i, Raw: raw.Journeys, Final: []model.Validated{}, Display: map[int]presentation.Result{}, Detail: raw.Detail, Batch: b, CoreNS: core, ServiceStart: start, SearchDone: done, ValidationStart: time.Since(sub).Nanoseconds()}
		if z.Raw == nil {
			z.Raw = []model.Journey{}
		}
		err := raw.Err
		var validationErr error
		complete := raw.Complete && err == nil
		capCertified := false
		if r.kind == "score_top_k" && raw.Detail != nil {
			v, e := comparison.RankCaps(checker, i.Query, raw.Detail.(csa.Result), *k, 300)
			validationErr = e
			z.Final = v.Candidates
			capCertified = v.StrictComplete
			complete = complete && capCertified
		} else {
			if r.kind == "arrival_top_k" && raw.Detail != nil {
				_, validationErr = comparison.CheckBinding(checker, i.Query, raw.Detail.(csa.Result))
			}
			if r.kind == "arrival_top_k" && raw.Complete && raw.Detail == nil {
				validationErr = fmt.Errorf("missing arrival certificate metadata")
			}
			for _, j := range z.Raw {
				if validationErr != nil {
					break
				}
				v, e := checker.Check(i.Query, j)
				if e != nil {
					validationErr = e
					break
				}
				z.Final = append(z.Final, v)
			}
		}
		if validationErr == nil {
			for _, displayK := range []int{1, 3, 5, 10} {
				v, e := presentation.Rank(i.Query, z.Final, displayK, 300)
				if e != nil {
					validationErr = e
					break
				}
				v.GlobalOptimalityClaim = capCertified && displayK <= *k
				z.Display[displayK] = v
			}
		}
		if validationErr == nil && qualityIndex != nil {
			begin := time.Now()
			js := []model.Journey{}
			for _, v := range z.Final {
				js = append(js, v.Journey)
			}
			var value recommend.Result
			var e error
			if choiceConfig == nil {
				value, e = qualityIndex.Evaluate(i.Query, js)
			} else {
				value, e = qualityIndex.EvaluateChoices(ctx, i.Query, js, *choiceConfig)
			}
			z.QualityNS = time.Since(begin).Nanoseconds()
			if e != nil && (errors.Is(e, recommend.ErrSelectionBudget) || errors.Is(e, context.DeadlineExceeded) || errors.Is(e, context.Canceled)) {
				err = e
				complete = false
			} else {
				validationErr = e
			}
			z.Quality = &value
		}
		z.ResponseNS = time.Since(sub).Nanoseconds()
		z.ValidationRankNS = z.ResponseNS - z.ValidationStart
		if validationErr != nil {
			err = fmt.Errorf("invalid witness/adapter: %w", validationErr)
			fatal = true
			z.Final = []model.Validated{}
			z.Display = map[int]presentation.Result{}
			complete = false
		}
		if prepErr == nil && (ctx.Err() != nil || z.ResponseNS > limit.Nanoseconds()) {
			if err == nil {
				err = fmt.Errorf("common submission deadline exceeded")
			}
			complete = false
		}
		if complete {
			z.Certificates.EA = true
			switch r.kind {
			case "pareto", "pareto_walking":
				z.Certificates.Walking = r.kind == "pareto_walking"
				z.Certificates.Pareto = true
				z.Certificates.Score = true
			case "score_top_k":
				z.Certificates.Pareto = true
				z.Certificates.Score = true
				z.Certificates.ScoreK = true
				z.Certificates.ScoreThroughK = *k
				z.Certificates.ArrivalThroughK = *k
				z.Certificates.ArrivalK = true
			case "arrival_top_k":
				z.Certificates.ArrivalK = true
				z.Certificates.ArrivalThroughK = *k
			}
		}
		if !complete {
			for key, v := range z.Display {
				v.GlobalOptimalityClaim = false
				z.Display[key] = v
			}
		}
		z.Completed = complete
		z.Attempted = prepErr == nil
		z.ValidEmpty = complete && len(z.Final) == 0
		if complete {
			for _, j := range z.Final {
				if j.Metrics.Boardings > 0 {
					z.Transit = true
					break
				}
			}
		}
		z.Status = status(err)
		if err != nil {
			z.Error = err.Error()
		}
		if prepErr != nil {
			z.Status = "not_run_preparation_unavailable"
			z.Error = prepErr.Error()
		}
		if !complete && err == nil {
			z.Status = "uncertified"
		}
		if z.Status == "routing_error" || z.Status == "correctness_mismatch" {
			fatal = true
		}
		return z
	}
	runPass := func(rep int, forced bool) error {
		items := append([]item{}, w.Items...)
		rng := rand.New(rand.NewPCG(w.Seed, uint64(rep)))
		rng.Shuffle(len(items), func(i, j int) { items[i], items[j] = items[j], items[i] })
		p := pass{Algorithm: *alg, Repetition: rep, Warmup: rep < *warm, Records: []record{}, Batches: []batchRecord{}}
		beginPass := time.Now()
		limit := *deadline
		if forced {
			limit = time.Nanosecond
		}
		for from := 0; from < len(items); from += *size {
			part := items[from:min(from+*size, len(items))]
			bi := from / *size
			br := batchRecord{ID: bi, Shared: r.shared != nil, QueryIDs: []string{}}
			for _, i := range part {
				br.QueryIDs = append(br.QueryIDs, i.Query.ID)
			}
			runtime.ReadMemStats(&before)
			submitted := time.Now()
			ctx, cancel := context.WithDeadline(context.Background(), submitted.Add(limit))
			if prepErr != nil {
				for _, i := range part {
					p.Records = append(p.Records, finalize(i, rawResult{Err: prepErr}, submitted, bi, nil, 0, 0, ctx, limit))
				}
			} else if r.shared != nil {
				qs := []model.Query{}
				for _, i := range part {
					qs = append(qs, i.Query)
				}
				start := time.Since(submitted).Nanoseconds()
				t := time.Now()
				raw, detail := r.shared(ctx, qs)
				br.CoreNS = time.Since(t).Nanoseconds()
				done := time.Since(submitted).Nanoseconds()
				br.Detail = detail
				if len(raw) != len(part) {
					cancel()
					return fmt.Errorf("shared adapter lost lanes")
				}
				for i, v := range raw {
					p.Records = append(p.Records, finalize(part[i], v, submitted, bi, nil, start, done, ctx, limit))
				}
			} else {
				for _, i := range part {
					start := time.Since(submitted).Nanoseconds()
					t := time.Now()
					raw := r.single(ctx, i.Query)
					core := time.Since(t).Nanoseconds()
					br.CoreNS += core
					done := time.Since(submitted).Nanoseconds()
					p.Records = append(p.Records, finalize(i, raw, submitted, bi, &core, start, done, ctx, limit))
				}
			}
			br.MakespanNS = time.Since(submitted).Nanoseconds()
			cancel()
			runtime.ReadMemStats(&after)
			br.Allocated = after.TotalAlloc - before.TotalAlloc
			br.Resources = experiment.SnapshotResources()
			p.Batches = append(p.Batches, br)
		}
		makespan := time.Since(beginPass).Nanoseconds()
		file := fmt.Sprintf("pass-%02d.json", rep)
		if forced {
			file = "forced-deadline.json"
		}
		io, e := experiment.WriteArtifact(filepath.Join(*out, file), p)
		if e != nil {
			return e
		}
		counts := map[string]int{}
		responses := []float64{}
		cores := []float64{}
		complete, attempted, validEmpty, transit := 0, 0, 0, 0
		allResponses := []float64{}
		for _, v := range p.Records {
			if v.Attempted {
				attempted++
				allResponses = append(allResponses, float64(v.ResponseNS))
			}
			if v.ValidEmpty {
				validEmpty++
			}
			if v.Transit {
				transit++
			}
			counts[v.Status]++
			if v.Completed {
				complete++
				responses = append(responses, float64(v.ResponseNS))
				if v.CoreNS != nil {
					cores = append(cores, float64(*v.CoreNS))
				}
			}
			if forced && v.Completed {
				fatal = true
			}
		}
		summary := map[string]any{"repetition": rep, "warmup": p.Warmup, "forced": forced, "file": file, "sha256": io.SHA256, "requested": len(items), "complete": complete, "attempted": attempted, "not_run": len(items) - attempted, "valid_empty": validEmpty, "transit": transit, "attempted_response_ns": evaluation.Summarize(allResponses), "statuses": counts, "makespan_ns": makespan, "completed_queries_per_second": float64(complete) * 1e9 / float64(makespan), "completed_response_ns": evaluation.Summarize(responses), "completed_individual_core_ns": evaluation.Summarize(cores)}
		summaries = append(summaries, summary)
		if !forced && rep >= *warm {
			qps = append(qps, float64(complete)*1e9/float64(makespan))
		}
		fmt.Println("pass", rep, "forced", forced, counts)
		return nil
	}
	for rep := 0; rep < *warm+*reps; rep++ {
		if e = runPass(rep, false); e != nil {
			return e
		}
	}
	if e = runPass(*warm+*reps, true); e != nil {
		return e
	}
	var ci any
	if len(qps) > 1 {
		v, e := experiment.ThroughputConfidence(qps, w.Seed)
		if e != nil {
			return e
		}
		ci = v
	}
	var finalCost any
	if r.cost != nil {
		finalCost = r.cost()
	}
	_, e = experiment.WriteArtifact(filepath.Join(*out, "summary.json"), map[string]any{"success": !fatal, "success_scope": "No malformed route/adapter/unknown routing failure; budget/unsupported/deadline rows retained. Cross-process quality audited separately.", "algorithm": *alg, "kind": r.kind, "configuration": r.config, "quality_preparation": qualityPrep, "quality_enabled": *quality, "preference_config": choiceConfig, "preference_config_sha256": preferenceSHA, "candidate_k": *k, "display_k": []int{1, 3, 5, 10}, "penalty": 300, "batch_size": *size, "repetitions": *reps, "warmups": *warm, "batch_deadline_ns": deadline.Nanoseconds(), "preparation_deadline_ns": prepTimeout.Nanoseconds(), "rss_sampled_safety_stop_bytes": *rssStop, "rss_sampling_interval_ns": int64(100000000), "hard_memory_cap": false, "hard_cpu_confinement": false, "gomaxprocs": runtime.GOMAXPROCS(0), "go_version": runtime.Version(), "goos": runtime.GOOS, "goarch": runtime.GOARCH, "hardware": os.Getenv("TRANSIT_BENCH_HARDWARE"), "provenance": prov, "dataset_sha256": dh, "queries_sha256": qh, "fixture_manifest_sha256": fixtureSHA, "scoped_configuration_sha256": scopedSHA, "seed": w.Seed, "method": w.Method, "input_load_ns": loadNS, "preparation": prep, "checker_preparation": checkPrep, "passes": summaries, "throughput_interval": ci, "index_cost_final": finalCost, "resources_final": experiment.SnapshotResources(), "scope": "Native development with recorded resources;8GB/four cores is a cost reference, not an acceptance gate. One router/process. Common batch submission deadline includes queue/search/validation/ranking. No divided shared-core latency; process RSS separate from cumulative allocations; no worker subprocesses."})
	if e != nil {
		return e
	}
	if fatal {
		return fmt.Errorf("invalid result or adapter failure; retained")
	}
	return nil
}
func main() {
	if e := run(); e != nil {
		fmt.Fprintln(os.Stderr, e)
		os.Exit(1)
	}
}
