// tadbench measures minimum-arrival TAD; reference frontiers are projected to minimum arrival.
package main

import (
	"context"
	"flag"
	"fmt"
	"github.com/ertyoii/transit-routing-bench/evaluation"
	"github.com/ertyoii/transit-routing-bench/experiment"
	"github.com/ertyoii/transit-routing-bench/fixtures"
	"github.com/ertyoii/transit-routing-go/eacsa"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/paper"
	"github.com/ertyoii/transit-routing-go/raptor"
	"github.com/ertyoii/transit-routing-go/strictjson"
	"github.com/ertyoii/transit-routing-go/tad"
	"github.com/ertyoii/transit-routing-go/validate"
	"math/rand/v2"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
	"time"
)

type Item struct {
	Stratum string      `json:"stratum"`
	Query   model.Query `json:"query"`
}
type Workload struct {
	Seed          uint64 `json:"seed"`
	Method        string `json:"method"`
	DatasetSHA256 string `json:"dataset_sha256"`
	Items         []Item `json:"items"`
}
type Record struct {
	Item
	Raw            []model.Journey   `json:"raw"`
	Final          []model.Validated `json:"final"`
	Complete       bool              `json:"complete"`
	Error          string            `json:"error,omitempty"`
	TimedOut       bool              `json:"timed_out"`
	CoreNS         int64             `json:"core_ns"`
	ResponseNS     int64             `json:"response_ns"`
	AllocatedBytes uint64            `json:"core_allocated_bytes"`
	Stats          any               `json:"stats"`
}
type Pass struct {
	Algorithm  string   `json:"algorithm"`
	Repetition int      `json:"repetition"`
	Warmup     bool     `json:"warmup"`
	Records    []Record `json:"records"`
}
type Summary struct {
	Algorithm       string                  `json:"algorithm"`
	Repetition      int                     `json:"repetition"`
	Warmup          bool                    `json:"warmup"`
	File            string                  `json:"file"`
	SHA256          string                  `json:"sha256"`
	Queries         int                     `json:"queries"`
	Errors          int                     `json:"errors"`
	Timeouts        int                     `json:"timeouts"`
	Core            evaluation.Distribution `json:"core_ns"`
	Response        evaluation.Distribution `json:"response_ns"`
	AllocatedBytes  uint64                  `json:"core_allocated_bytes"`
	TotalResponseNS int64                   `json:"sum_response_ns"`
	PassMakespanNS  int64                   `json:"query_pass_makespan_ns"`
	Throughput      float64                 `json:"successful_throughput_qps"`
}

func read(p string, v any) (string, error) {
	b, e := os.ReadFile(p)
	if e != nil {
		return "", e
	}
	if e = strictjson.Decode(b, v); e != nil {
		return "", e
	}
	return fixtures.Sum(b), nil
}
func objective(q model.Query, vs []model.Validated) int64 {
	best := paper.Infinity
	for _, v := range vs {
		best = min(best, v.Metrics.Arrival)
	}
	return best
}
func run() error {
	dataset := flag.String("dataset", "", "normalized model")
	queries := flag.String("queries", "", "frozen workload")
	out := flag.String("out-dir", "", "new output directory")
	reps := flag.Int("repetitions", 3, "measured repetitions")
	warmups := flag.Int("warmups", 1, "retained warmups")
	timeout := flag.Duration("timeout", 5*time.Second, "per-query cooperative core deadline")
	maxLabels := flag.Int("max-labels", 2000000, "TAD insertion budget")
	maxVisits := flag.Int("max-visits", 10000000, "TAD connection visit budget")
	maxWalkVisits := flag.Int("max-walk-visits", 10000000, "TAD raw walking-edge visit budget")
	hardware := flag.String("hardware", "unrecorded", "verified host description")
	flag.Parse()
	if *dataset == "" || *queries == "" || *out == "" || *reps < 1 || *warmups < 0 || *timeout <= 0 {
		return fmt.Errorf("invalid arguments")
	}
	if e := os.Mkdir(*out, 0700); e != nil {
		return e
	}
	start := time.Now()
	var d model.Dataset
	var w Workload
	dh, e := read(*dataset, &d)
	if e != nil {
		return e
	}
	qh, e := read(*queries, &w)
	if e != nil {
		return e
	}
	if w.DatasetSHA256 != dh || len(w.Items) == 0 {
		return fmt.Errorf("workload hash mismatch or empty")
	}
	loadNS := time.Since(start).Nanoseconds()
	seen := map[string]bool{}
	for _, i := range w.Items {
		if seen[i.Query.ID] {
			return fmt.Errorf("duplicate query ID")
		}
		seen[i.Query.ID] = true
		if e = i.Query.Validate(d); e != nil {
			return e
		}
	}
	provenance, e := experiment.Identify(".")
	if e != nil {
		return e
	}
	prep := map[string]any{}
	var before, after runtime.MemStats
	measure := func(name string, f func() error) error {
		runtime.ReadMemStats(&before)
		t := time.Now()
		e := f()
		ns := time.Since(t).Nanoseconds()
		runtime.ReadMemStats(&after)
		message := ""
		if e != nil {
			message = e.Error()
		}
		prep[name] = map[string]any{"elapsed_ns": ns, "allocated_bytes": after.TotalAlloc - before.TotalAlloc, "error": message, "resources_after": experiment.SnapshotResources()}
		return e
	}
	var ea *eacsa.Index
	var rap *raptor.Index
	var td *tad.Index
	var checker *validate.Checker
	if e = measure("ea_csa", func() error { var e error; ea, e = eacsa.New(d); return e }); e != nil {
		return e
	}
	if e = measure("raptor", func() error { var e error; rap, e = raptor.New(d); return e }); e != nil {
		return e
	}
	if e = measure("tad", func() error { var e error; td, e = tad.New(d); return e }); e != nil {
		return e
	}
	if e = measure("independent_checker", func() error { var e error; checker, e = validate.New(d); return e }); e != nil {
		return e
	}
	cfg := tad.Config{MaxLabels: *maxLabels, MaxConnectionVisits: *maxVisits, MaxWalkVisits: *maxWalkVisits}

	summaries := []Summary{}
	comparisons := []any{}
	allOK := true
	for rep := 0; rep < *warmups+*reps; rep++ {
		items := append([]Item{}, w.Items...)
		rng := rand.New(rand.NewPCG(w.Seed, uint64(rep)))
		rng.Shuffle(len(items), func(i, j int) { items[i], items[j] = items[j], items[i] })
		names := []string{"ea_csa", "raptor", "tad"}
		names = append(names[rep%3:], names[:rep%3]...)
		paired := map[string]map[string]Record{}
		for _, name := range names {
			p := Pass{Algorithm: name, Repetition: rep, Warmup: rep < *warmups, Records: []Record{}}
			paired[name] = map[string]Record{}
			passBegin := time.Now()
			for _, item := range items {
				r := Record{Item: item, Raw: []model.Journey{}, Final: []model.Validated{}}
				runtime.ReadMemStats(&before)
				begin := time.Now()
				ctx, cancel := context.WithTimeout(context.Background(), *timeout)
				coreStart := time.Now()
				if name == "tad" {
					result, e := td.Search(ctx, item.Query, cfg)
					r.Raw, r.Complete, r.Error, r.Stats = result.Journeys, result.Complete, result.Error, result.Stats
					if e != nil && r.Error == "" {
						r.Error = e.Error()
					}

				} else {
					var result paper.Result
					var e error
					if name == "ea_csa" {
						result, e = ea.Search(ctx, item.Query)
					} else {
						result, e = rap.Search(ctx, item.Query)
					}
					r.Raw, r.Complete, r.Error, r.Stats = result.Journeys, result.Complete, result.Error, result.Stats
					if e != nil && r.Error == "" {
						r.Error = e.Error()
					}
				}
				r.CoreNS = time.Since(coreStart).Nanoseconds()
				runtime.ReadMemStats(&after)
				r.AllocatedBytes = after.TotalAlloc - before.TotalAlloc
				cancel()
				if r.CoreNS > timeout.Nanoseconds() {
					r.Complete = false
					if !strings.Contains(r.Error, context.DeadlineExceeded.Error()) {
						r.Error += "; " + context.DeadlineExceeded.Error() + " (measured core overrun)"
					}
				}
				r.TimedOut = strings.Contains(r.Error, context.DeadlineExceeded.Error())
				if !r.Complete && r.Error == "" {
					r.Error = "incomplete result without a completion certificate"
				}
				for _, j := range r.Raw {
					v, e := checker.Check(item.Query, j)
					if e != nil {
						r.Error += "; invalid witness: " + e.Error()
						r.Complete = false
					} else {
						r.Final = append(r.Final, v)
					}
				}
				if name == "tad" && len(r.Raw) > 1 {
					r.Complete = false
					r.Error += "; multiple representatives for single EA output"
				}

				r.ResponseNS = time.Since(begin).Nanoseconds()
				p.Records = append(p.Records, r)
				paired[name][item.Query.ID] = r
			}
			s := Summary{Algorithm: name, Repetition: rep, Warmup: p.Warmup, Queries: len(p.Records), PassMakespanNS: time.Since(passBegin).Nanoseconds()}
			core, response := []float64{}, []float64{}
			for _, r := range p.Records {
				if r.Error != "" {
					s.Errors++
					allOK = false
				}
				if r.TimedOut {
					s.Timeouts++
				}
				core = append(core, float64(r.CoreNS))
				response = append(response, float64(r.ResponseNS))
				s.TotalResponseNS += r.ResponseNS
				s.AllocatedBytes += r.AllocatedBytes
			}
			s.Core = evaluation.Summarize(core)
			s.Response = evaluation.Summarize(response)
			s.Throughput = float64(s.Queries-s.Errors) * 1e9 / float64(s.PassMakespanNS)
			s.File = fmt.Sprintf("%02d-%s.json", rep, name)
			io, e := experiment.WriteArtifact(filepath.Join(*out, s.File), p)
			if e != nil {
				return e
			}
			s.SHA256 = io.SHA256
			summaries = append(summaries, s)
			fmt.Printf("%s rep=%d queries=%d errors=%d p50=%.2fms p95=%.2fms\n", name, rep, s.Queries, s.Errors, s.Response.P50/1e6, s.Response.P95/1e6)
		}
		for _, i := range items {
			a, b, c := paired["ea_csa"][i.Query.ID], paired["raptor"][i.Query.ID], paired["tad"][i.Query.ID]
			available := a.Complete && a.Error == "" && b.Complete && b.Error == "" && reflect.DeepEqual(objective(i.Query, a.Final), objective(i.Query, b.Final))
			assessed := available && c.Complete && c.Error == ""
			equal := assessed && reflect.DeepEqual(objective(i.Query, a.Final), objective(i.Query, c.Final))
			if !available || !assessed || !equal {
				allOK = false
			}
			comparisons = append(comparisons, map[string]any{"repetition": rep, "warmup": rep < *warmups, "query_id": i.Query.ID, "reference_available": available, "tad_earliest_arrival_assessed": assessed, "equal_earliest_arrival": equal, "reference_minimum_arrival": objective(i.Query, a.Final), "tad_minimum_arrival": objective(i.Query, c.Final), "tad_error": c.Error})
		}
	}
	intervals := map[string]experiment.Interval{}
	samples := map[string][]float64{}
	for _, s := range summaries {
		if !s.Warmup {
			samples[s.Algorithm] = append(samples[s.Algorithm], s.Throughput)
		}
	}
	for name, ss := range samples {
		if len(ss) >= 2 {
			ci, e := experiment.ThroughputConfidence(ss, w.Seed)
			if e != nil {
				return e
			}
			ci.Statistic = "mean_sequential_query_throughput_qps"
			intervals[name] = ci
		}
	}
	manifest := map[string]any{
		"success": allOK, "dataset_sha256": dh, "workload_sha256": qh, "workload": w, "provenance": provenance,
		"output_contracts":                    map[string]string{"tad": "one_earliest_arrival_witness_under_boarding_cap", "ea_csa": "arrival_boardings_pareto_representatives", "raptor": "arrival_boardings_pareto_representatives"},
		"comparison_contract":                 "minimum arrival under identical hard boarding/walking limits; references compute extra Pareto information, so no equal-work speed comparison",
		"independent_earliest_arrival_oracle": "finite synthetic whole-word corpus; not applied to the full model workload",
		"go_version":                          runtime.Version(), "goos": runtime.GOOS, "goarch": runtime.GOARCH, "gomaxprocs": runtime.GOMAXPROCS(0), "hardware": *hardware, "created_utc": time.Now().UTC().Format(time.RFC3339Nano),
		"input_load_ns": loadNS, "preparation": prep, "tad_config": cfg, "timeout_ns": timeout.Nanoseconds(), "warmups": *warmups, "repetitions": *reps,
		"summaries": summaries, "comparisons": comparisons, "throughput_intervals": intervals, "resources_final": experiment.SnapshotResources(),
		"notes": []string{
			"TAD scans whole trip suffixes and relaxes raw walking edges. Stop-pair transfer and walking resources use declared expanded states; no scalar penalty or strict top-k applies.",
			"EA-CSA and RAPTOR are projected to minimum arrival under identical feasibility. Their additional Pareto output is different work; no equal-work performance claim. Large-model agreement is not independent oracle proof.",
			"Core includes raw walking/trip scans/reconstruction; response includes independent complete witness checking. Loading, all three separate indices, checker and serialization costs are recorded. Current Singapore input contains proxy/OSM closure edges, not the full raw street graph.",
			"Actual pass makespan determines throughput; never divide it to invent individual latency. Failures remain in every denominator. Allocations are cumulative deltas, peak RSS includes all algorithms and previous operations.",
			"Three repeated passes on an uncontrolled shared host and a reused modeled workload cannot establish population performance or Singapore service validity. Unknown accessibility and unverified street connectors remain limitations.",
		},
	}

	if _, e = experiment.WriteArtifact(filepath.Join(*out, "manifest.json"), manifest); e != nil {
		return e
	}
	if !allOK {
		return fmt.Errorf("comparison has failures, unsupported queries, or mismatches; full evidence retained")
	}
	return nil
}
func main() {
	if e := run(); e != nil {
		fmt.Fprintln(os.Stderr, e)
		os.Exit(1)
	}
}
