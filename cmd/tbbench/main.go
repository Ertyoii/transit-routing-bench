// tbbench compares supported arrival/boarding frontiers; it never labels them top-k.
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
	"github.com/ertyoii/transit-routing-go/tripbased"
	"github.com/ertyoii/transit-routing-go/validate"
	"math/rand/v2"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"slices"
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
type key struct {
	Buffer     int64
	Accessible bool
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
func objective(q model.Query, vs []model.Validated) []int64 {
	a := make([]int64, q.MaxBoardings+1)
	for i := range a {
		a[i] = paper.Infinity
	}
	for _, v := range vs {
		for b := v.Metrics.Boardings; b < len(a); b++ {
			a[b] = min(a[b], v.Metrics.Arrival)
		}
	}
	return a
}
func run() error {
	dataset := flag.String("dataset", "", "normalized model")
	queries := flag.String("queries", "", "frozen workload")
	out := flag.String("out-dir", "", "new output directory")
	reps := flag.Int("repetitions", 3, "measured repetitions")
	warmups := flag.Int("warmups", 1, "retained warmups")
	timeout := flag.Duration("timeout", 5*time.Second, "per-query cooperative core deadline")
	prepTimeout := flag.Duration("prep-timeout", 60*time.Second, "per Trip-Based index preparation deadline")
	maxTransfers := flag.Int("max-transfers", 5000000, "fail-on-truncation preprocessing budget")
	maxSegments := flag.Int("max-segments", 1000000, "per-query queue budget")
	walk := flag.Int64("prepared-transfer-walk", 600, "index intermediate walking bound; query egress must also cover query transfer limit")
	hardware := flag.String("hardware", "unrecorded", "verified host description")
	flag.Parse()
	if *dataset == "" || *queries == "" || *out == "" || *reps < 1 || *warmups < 0 || *timeout <= 0 || *prepTimeout <= 0 {
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
	keys := []key{}
	for _, i := range w.Items {
		if seen[i.Query.ID] {
			return fmt.Errorf("duplicate query ID")
		}
		seen[i.Query.ID] = true
		if e = i.Query.Validate(d); e != nil {
			return e
		}
		k := key{i.Query.TransferBuffer, i.Query.AccessibleOnly}
		if !slices.Contains(keys, k) {
			keys = append(keys, k)
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
	var checker *validate.Checker
	if e = measure("ea_csa", func() error { var e error; ea, e = eacsa.New(d); return e }); e != nil {
		return e
	}
	if e = measure("raptor", func() error { var e error; rap, e = raptor.New(d); return e }); e != nil {
		return e
	}
	if e = measure("independent_checker", func() error { var e error; checker, e = validate.New(d); return e }); e != nil {
		return e
	}
	tb := map[key]*tripbased.Index{}
	prepErrors := map[key]string{}
	tbMetadata := []any{}
	for _, k := range keys {
		name := fmt.Sprintf("trip_based-buffer%d-accessible%t", k.Buffer, k.Accessible)
		cfg := tripbased.Config{TransferWalkingLimit: *walk, TransferBuffer: k.Buffer, AccessibleOnly: k.Accessible, MaxTransfers: *maxTransfers, MaxQueuedSegments: *maxSegments}
		err := measure(name, func() error {
			ctx, cancel := context.WithTimeout(context.Background(), *prepTimeout)
			defer cancel()
			t := time.Now()
			idx, e := tripbased.New(ctx, d, cfg)
			if time.Since(t) > *prepTimeout {
				return fmt.Errorf("preprocessing deadline overrun")
			}
			if e == nil {
				tb[k] = idx
			}
			return e
		})
		if err != nil {
			prepErrors[k] = err.Error()
			tbMetadata = append(tbMetadata, map[string]any{"name": name, "config": cfg, "error": err.Error()})
		} else {
			tbMetadata = append(tbMetadata, map[string]any{"name": name, "capability": tb[k].Capabilities(), "counts": tb[k].Preparation()})
		}
	}
	summaries := []Summary{}
	comparisons := []any{}
	allOK := len(prepErrors) == 0
	for rep := 0; rep < *warmups+*reps; rep++ {
		items := append([]Item{}, w.Items...)
		rng := rand.New(rand.NewPCG(w.Seed, uint64(rep)))
		rng.Shuffle(len(items), func(i, j int) { items[i], items[j] = items[j], items[i] })
		names := []string{"ea_csa", "raptor", "trip_based"}
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
				if name == "trip_based" {
					k := key{item.Query.TransferBuffer, item.Query.AccessibleOnly}
					if msg := prepErrors[k]; msg != "" {
						r.Error = "preprocessing unavailable: " + msg
					} else {
						result, e := tb[k].Search(ctx, item.Query)
						r.Raw, r.Complete, r.Error, r.Stats = result.Journeys, result.Complete, result.Error, result.Stats
						if e != nil && r.Error == "" {
							r.Error = e.Error()
						}
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
			a, b, c := paired["ea_csa"][i.Query.ID], paired["raptor"][i.Query.ID], paired["trip_based"][i.Query.ID]
			available := a.Complete && a.Error == "" && b.Complete && b.Error == "" && reflect.DeepEqual(objective(i.Query, a.Final), objective(i.Query, b.Final))
			assessed := available && c.Complete && c.Error == ""
			equal := assessed && reflect.DeepEqual(objective(i.Query, a.Final), objective(i.Query, c.Final))
			if !available || !assessed || !equal {
				allOK = false
			}
			comparisons = append(comparisons, map[string]any{"repetition": rep, "warmup": rep < *warmups, "query_id": i.Query.ID, "reference_available": available, "trip_based_assessed": assessed, "equal_frontier": equal, "reference_vector": objective(i.Query, a.Final), "trip_based_vector": objective(i.Query, c.Final), "trip_based_error": c.Error})
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
			intervals[name] = ci
		}
	}
	manifest := map[string]any{"success": allOK, "dataset_sha256": dh, "workload_sha256": qh, "workload": w, "provenance": provenance, "output_contract": "arrival_boardings_pareto_representatives; not strict top-k or all identities", "go_version": runtime.Version(), "goos": runtime.GOOS, "goarch": runtime.GOARCH, "gomaxprocs": runtime.GOMAXPROCS(0), "hardware": *hardware, "created_utc": time.Now().UTC().Format(time.RFC3339Nano), "input_load_ns": loadNS, "preparation": prep, "trip_based_preparation": tbMetadata, "timeout_ns": timeout.Nanoseconds(), "prep_timeout_ns": prepTimeout.Nanoseconds(), "warmups": *warmups, "repetitions": *reps, "summaries": summaries, "comparisons": comparisons, "throughput_intervals": intervals, "resources_final": experiment.SnapshotResources(), "notes": []string{"All three kernels return arrival/boarding Pareto representatives. Complete concerns that objective, not the full journey universe or strict top-k.", "Core includes query-local walking and reconstruction; response adds independent witness validation. Both exclude loading/index preparation and serialization, with IO sidecars saved.", "Sequential per-query timings; no batch algorithm or fabricated shared latency. Failures/unsupported queries stay in workload, timing and explicit comparison coverage.", "Preprocessing budget exhaustion returns no Trip-Based index; deadlines are cooperative with measured overrun classification. Index accessibility/buffer are fixed; queries are checked against the supported profile.", "Allocated bytes are cumulative call deltas, not retained heap/peak. Resource snapshots include all indices/passes/previous IO in this process. Three repetitions and uncontrolled background/thermal state limit performance conclusions.", "The three kernels share paper walking preprocessing and static transfer rules; independent full-word and itinerary tests provide separate correctness evidence. Model results and unverified street connectors do not establish field accuracy."}}
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
