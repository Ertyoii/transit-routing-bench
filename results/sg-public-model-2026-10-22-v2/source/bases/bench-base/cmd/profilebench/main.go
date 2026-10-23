// profilebench compares complete ready-time windows, never a profile against one
// point query. Compact raw profiles and every integer-time objective grid survive.
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
	"github.com/ertyoii/transit-routing-go/profilecsa"
	"github.com/ertyoii/transit-routing-go/profilequery"
	"github.com/ertyoii/transit-routing-go/raptor"
	"github.com/ertyoii/transit-routing-go/strictjson"
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
	Stratum string             `json:"stratum"`
	Query   profilequery.Query `json:"query"`
}
type workload struct {
	Seed          uint64 `json:"seed"`
	Method        string `json:"method"`
	DatasetSHA256 string `json:"dataset_sha256"`
	Items         []item `json:"items"`
}
type point struct {
	LatestReady int64           `json:"latest_ready"`
	Validated   model.Validated `json:"validated"`
}
type grid struct {
	Ready  int64   `json:"ready"`
	Vector []int64 `json:"arrival_under_boarding_caps"`
}
type record struct {
	item
	Raw                  profilequery.Result `json:"raw"`
	FinalPoints          []point             `json:"final_points"`
	Direct               *model.Validated    `json:"final_direct,omitempty"`
	Grid                 []grid              `json:"every_integer_ready_time"`
	ValidatedOccurrences int                 `json:"validated_witness_occurrences"`
	Complete             bool                `json:"complete"`
	Error                string              `json:"error,omitempty"`
	TimedOut             bool                `json:"timed_out"`
	CoreNS               int64               `json:"core_ns"`
	ResponseNS           int64               `json:"response_ns"`
	Allocated            uint64              `json:"core_allocated_bytes"`
}
type pass struct {
	Algorithm  string   `json:"algorithm"`
	Repetition int      `json:"repetition"`
	Warmup     bool     `json:"warmup"`
	Records    []record `json:"records"`
}
type summary struct {
	Algorithm     string                  `json:"algorithm"`
	Repetition    int                     `json:"repetition"`
	Warmup        bool                    `json:"warmup"`
	File          string                  `json:"file"`
	SHA256        string                  `json:"sha256"`
	Queries       int                     `json:"profile_queries"`
	ReadyTimes    int                     `json:"ready_time_observations"`
	Errors        int                     `json:"errors"`
	Timeouts      int                     `json:"timeouts"`
	Core          evaluation.Distribution `json:"core_ns"`
	Response      evaluation.Distribution `json:"response_ns"`
	PassNS        int64                   `json:"query_pass_makespan_ns"`
	SumResponseNS int64                   `json:"sum_response_ns"`
	Allocated     uint64                  `json:"core_allocated_bytes"`
	Throughput    float64                 `json:"successful_profiles_per_second"`
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
func verify(r *record, checker *validate.Checker) error {
	for _, p := range r.Raw.Points {
		q := r.Query.Base
		q.Departure = p.LatestReady
		if p.LatestReady < r.Query.Base.Departure || p.LatestReady > r.Query.End {
			return fmt.Errorf("point outside ready window")
		}
		v, e := checker.Check(q, p.Journey)
		if e != nil {
			return e
		}
		if v.Metrics.Arrival != p.Arrival || v.Metrics.Boardings != p.Boardings {
			return fmt.Errorf("point metadata differs from full itinerary")
		}
		r.FinalPoints = append(r.FinalPoints, point{p.LatestReady, v})
		r.ValidatedOccurrences++
	}
	if r.Raw.Direct != nil {
		v, e := checker.Check(r.Query.Base, r.Raw.Direct.Journey)
		if e != nil {
			return e
		}
		if v.Metrics.Boardings != 0 || v.Metrics.Arrival-r.Query.Base.Departure != r.Raw.Direct.Duration {
			return fmt.Errorf("invalid direct affine branch")
		}
		r.Direct = &v
		r.ValidatedOccurrences++
	}
	if !r.Complete {
		return nil
	}
	for ready := r.Query.Base.Departure; ready <= r.Query.End; ready++ {
		js, e := r.Raw.At(ready)
		if e != nil {
			return e
		}
		q := r.Query.Base
		q.Departure = ready
		vector := make([]int64, q.MaxBoardings+1)
		for b := range vector {
			vector[b] = paper.Infinity
		}
		for _, j := range js {
			v, e := checker.Check(q, j)
			if e != nil {
				return e
			}
			r.ValidatedOccurrences++
			for b := v.Metrics.Boardings; b < len(vector); b++ {
				vector[b] = min(vector[b], v.Metrics.Arrival)
			}
		}
		r.Grid = append(r.Grid, grid{ready, vector})
	}
	return nil
}
func run() error {
	dataset := flag.String("dataset", "", "normalized dataset")
	queries := flag.String("queries", "", "frozen profile queries")
	out := flag.String("out-dir", "", "new directory")
	warmups := flag.Int("warmups", 1, "retained warmups")
	reps := flag.Int("repetitions", 3, "measured repetitions")
	timeout := flag.Duration("timeout", 5*time.Second, "cooperative core deadline")
	visits := flag.Int("max-visits", 10000000, "connection visit bound")
	labels := flag.Int("max-labels", 2000000, "label update bound")
	departures := flag.Int("max-departures", 10000, "range departure iteration bound")
	maxSpan := flag.Int64("max-window-seconds", 600, "bounded complete integer-grid validation span")
	hardware := flag.String("hardware", "unrecorded", "verified host description")
	flag.Parse()
	if *dataset == "" || *queries == "" || *out == "" || *reps < 1 || *warmups < 0 || *timeout <= 0 || *maxSpan < 0 {
		return fmt.Errorf("invalid arguments")
	}
	if e := os.Mkdir(*out, 0700); e != nil {
		return e
	}
	loadStart := time.Now()
	var d model.Dataset
	var w workload
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
	loadNS := time.Since(loadStart).Nanoseconds()
	seen := map[string]bool{}
	for _, i := range w.Items {
		q := i.Query
		if seen[q.Base.ID] {
			return fmt.Errorf("duplicate query")
		}
		seen[q.Base.ID] = true
		if e = q.Base.Validate(d); e != nil {
			return e
		}
		if q.End < q.Base.Departure || q.End > q.Base.LatestArrival || q.End-q.Base.Departure > *maxSpan {
			return fmt.Errorf("invalid or over-budget verification window")
		}
	}
	provenance, e := experiment.Identify(".")
	if e != nil {
		return e
	}
	var before, after runtime.MemStats
	prep := map[string]any{}
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
	var csa *profilecsa.Index
	var rap *raptor.Index
	var checker *validate.Checker
	if e = measure("profile_csa", func() error { var e error; csa, e = profilecsa.New(d); return e }); e != nil {
		return e
	}
	if e = measure("range_raptor", func() error { var e error; rap, e = raptor.New(d); return e }); e != nil {
		return e
	}
	if e = measure("independent_checker", func() error { var e error; checker, e = validate.New(d); return e }); e != nil {
		return e
	}
	limits := profilequery.Limits{MaxConnectionVisits: *visits, MaxLabels: *labels, MaxDepartures: *departures}
	summaries := []summary{}
	comparisons := []any{}
	allOK := true
	for rep := 0; rep < *warmups+*reps; rep++ {
		items := append([]item{}, w.Items...)
		rng := rand.New(rand.NewPCG(w.Seed, uint64(rep)))
		rng.Shuffle(len(items), func(i, j int) { items[i], items[j] = items[j], items[i] })
		names := []string{"profile_csa", "range_raptor"}
		if rep%2 == 1 {
			names[0], names[1] = names[1], names[0]
		}
		paired := map[string]map[string]record{}
		for _, name := range names {
			p := pass{Algorithm: name, Repetition: rep, Warmup: rep < *warmups, Records: []record{}}
			paired[name] = map[string]record{}
			beginPass := time.Now()
			for _, i := range items {
				r := record{item: i, FinalPoints: []point{}, Grid: []grid{}}
				runtime.ReadMemStats(&before)
				begin := time.Now()
				ctx, cancel := context.WithTimeout(context.Background(), *timeout)
				core := time.Now()
				if name == "profile_csa" {
					r.Raw, e = csa.Search(ctx, i.Query, limits)
				} else {
					r.Raw, e = rap.SearchRange(ctx, i.Query, limits)
				}
				r.CoreNS = time.Since(core).Nanoseconds()
				runtime.ReadMemStats(&after)
				r.Allocated = after.TotalAlloc - before.TotalAlloc
				cancel()
				r.Complete = r.Raw.Complete
				r.Error = r.Raw.Error
				if e != nil && r.Error == "" {
					r.Error = e.Error()
				}
				if !r.Complete && r.Error == "" {
					r.Error = "incomplete without completion certificate"
				}
				if r.CoreNS > timeout.Nanoseconds() {
					r.Complete = false
					r.Error += "; " + context.DeadlineExceeded.Error() + " (measured core overrun)"
				}
				r.TimedOut = strings.Contains(r.Error, context.DeadlineExceeded.Error())
				if e := verify(&r, checker); e != nil {
					r.Complete = false
					r.Error += "; independent validation: " + e.Error()
				}
				r.ResponseNS = time.Since(begin).Nanoseconds()
				p.Records = append(p.Records, r)
				paired[name][i.Query.Base.ID] = r
			}
			s := summary{Algorithm: name, Repetition: rep, Warmup: p.Warmup, Queries: len(p.Records), PassNS: time.Since(beginPass).Nanoseconds()}
			cores, responses := []float64{}, []float64{}
			for _, r := range p.Records {
				if r.Error != "" || !r.Complete {
					s.Errors++
					allOK = false
				}
				if r.TimedOut {
					s.Timeouts++
				}
				s.ReadyTimes += len(r.Grid)
				cores = append(cores, float64(r.CoreNS))
				responses = append(responses, float64(r.ResponseNS))
				s.SumResponseNS += r.ResponseNS
				s.Allocated += r.Allocated
			}
			s.Core = evaluation.Summarize(cores)
			s.Response = evaluation.Summarize(responses)
			s.Throughput = float64(s.Queries-s.Errors) * 1e9 / float64(s.PassNS)
			s.File = fmt.Sprintf("%02d-%s.json", rep, name)
			io, e := experiment.WriteArtifact(filepath.Join(*out, s.File), p)
			if e != nil {
				return e
			}
			s.SHA256 = io.SHA256
			summaries = append(summaries, s)
			fmt.Printf("%s rep=%d profiles=%d errors=%d grid=%d core p50/p95 %.2f/%.2fms response %.2f/%.2fms\n", name, rep, s.Queries, s.Errors, s.ReadyTimes, s.Core.P50/1e6, s.Core.P95/1e6, s.Response.P50/1e6, s.Response.P95/1e6)
		}
		for _, i := range items {
			a, b := paired["profile_csa"][i.Query.Base.ID], paired["range_raptor"][i.Query.Base.ID]
			assessed := a.Complete && a.Error == "" && b.Complete && b.Error == ""
			equal := assessed && reflect.DeepEqual(a.Grid, b.Grid)
			if !equal {
				allOK = false
			}
			comparisons = append(comparisons, map[string]any{"query_id": i.Query.Base.ID, "repetition": rep, "warmup": rep < *warmups, "assessed": assessed, "equal_whole_window": equal, "window_integer_seconds": i.Query.End - i.Query.Base.Departure + 1, "profile_csa_error": a.Error, "range_raptor_error": b.Error})
		}
	}
	samples := map[string][]float64{}
	intervals := map[string]experiment.Interval{}
	for _, s := range summaries {
		if !s.Warmup {
			samples[s.Algorithm] = append(samples[s.Algorithm], s.Throughput)
		}
	}
	for name, ss := range samples {
		if len(ss) > 1 {
			ci, e := experiment.ThroughputConfidence(ss, w.Seed)
			if e != nil {
				return e
			}
			ci.Statistic = "mean_sequential_profiles_per_second"
			intervals[name] = ci
		}
	}
	m := map[string]any{"success": allOK, "contract": "ready_window_arrival_boardings_v1", "dataset_sha256": dh, "workload_sha256": qh, "workload": w, "provenance": provenance, "go_version": runtime.Version(), "goos": runtime.GOOS, "goarch": runtime.GOARCH, "gomaxprocs": runtime.GOMAXPROCS(0), "hardware": *hardware, "created_utc": time.Now().UTC().Format(time.RFC3339Nano), "input_load_ns": loadNS, "preparation": prep, "raptor_preparation": rap.Preparation(), "limits": limits, "core_timeout_ns": timeout.Nanoseconds(), "max_verification_window_seconds": *maxSpan, "warmups": *warmups, "repetitions": *reps, "summaries": summaries, "comparisons": comparisons, "throughput_intervals": intervals, "resources_final": experiment.SnapshotResources(), "notes": []string{"Both algorithms solve identical full ready-time windows with a fixed arrival horizon, separate direct affine branch, and arrival/boarding objective. Not strict top-k.", "Core includes candidate-time construction, walking, search, reconstruction and profile normalization. Response adds complete point/direct witness validation and every integer-ready-time lookup/witness validation. Both exclude input/index preparation and result serialization; IO sidecars retained.", "Saved compact raw profiles and validated points reconstruct every grid answer. Every materialized grid witness is validated; grid files store vectors, not redundant copies of those itineraries.", "Profile query latency is not divided by grid size. Throughput uses actual sequential profile-pass makespan. Failures retain original request denominators; paired coverage is explicit.", "Common preprocessing and materialization are shared and require independent specification/review. Allocations are cumulative deltas; peak RSS is whole-process cumulative, not isolated by algorithm. Three repetitions and uncontrolled shared host limit inference.", "Modeled frequency timetable and unverified OSM connectors do not establish actual Singapore service validity. Regional gate remains closed."}}
	if _, e = experiment.WriteArtifact(filepath.Join(*out, "manifest.json"), m); e != nil {
		return e
	}
	if !allOK {
		return fmt.Errorf("profile comparison has incomplete, invalid or mismatched windows; evidence retained")
	}
	return nil
}
func main() {
	if e := run(); e != nil {
		fmt.Fprintln(os.Stderr, e)
		os.Exit(1)
	}
}
