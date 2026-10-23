// Package experiment records reproducible oracle smoke runs. It is not a batched CSA.
package experiment

import (
	"context"
	"fmt"
	"github.com/ertyoii/transit-routing-bench/fixtures"
	"github.com/ertyoii/transit-routing-bench/oracle"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/presentation"
	"github.com/ertyoii/transit-routing-go/selection"
	"github.com/ertyoii/transit-routing-go/validate"
	"math/rand/v2"
	"runtime"
	"slices"
	"time"
)

type Config struct {
	Repetitions     int           `json:"repetitions"`
	Warmups         int           `json:"warmups"`
	Seed            uint64        `json:"seed"`
	Limits          oracle.Limits `json:"oracle_limits"`
	K               int           `json:"k"`
	CandidateCap    int           `json:"candidate_cap"`
	TransferPenalty int64         `json:"ranking_transfer_penalty_seconds"`
}
type QueryRun struct {
	Query                  model.Query                         `json:"query"`
	BatchOffsetStartedNS   int64                               `json:"batch_offset_started_ns"`
	BatchOffsetCompletedNS int64                               `json:"batch_offset_completed_ns"`
	CoreNS                 int64                               `json:"core_ns"`
	EndToEndNS             int64                               `json:"end_to_end_ns"`
	Raw                    oracle.Result                       `json:"raw"`
	Validated              []model.Validated                   `json:"validated"`
	Final                  map[selection.Mode]selection.Result `json:"final"`
	Presentation           presentation.Result                 `json:"presentation"`
	Errors                 []string                            `json:"errors"`
}
type BatchRun struct {
	Index             int        `json:"index"`
	Warmup            bool       `json:"warmup"`
	MakespanNS        int64      `json:"makespan_ns"`
	SuccessfulQueries int        `json:"successful_queries"`
	ThroughputQPS     float64    `json:"throughput_qps"`
	Queries           []QueryRun `json:"queries"`
}
type Memory struct {
	HeapAllocBytes  uint64 `json:"heap_alloc_bytes"`
	TotalAllocBytes uint64 `json:"total_alloc_bytes"`
	NumGC           uint32 `json:"num_gc"`
}
type Interval struct {
	Statistic   string  `json:"statistic"`
	Mean        float64 `json:"mean"`
	Lower95     float64 `json:"lower_95"`
	Upper95     float64 `json:"upper_95"`
	Resamples   int     `json:"resamples"`
	SampleCount int     `json:"sample_count"`
	Method      string  `json:"method"`
}
type ProcessUsage struct {
	Available        bool    `json:"available"`
	MaxRSSBytes      int64   `json:"max_rss_bytes"`
	UserCPUSeconds   float64 `json:"user_cpu_seconds"`
	SystemCPUSeconds float64 `json:"system_cpu_seconds"`
	Scope            string  `json:"scope"`
	Error            string  `json:"error,omitempty"`
}

type Report struct {
	Errors               []string          `json:"errors"`
	InputQueries         []model.Query     `json:"input_queries"`
	Provenance           Provenance        `json:"provenance"`
	SchemaVersion        string            `json:"schema_version"`
	CreatedUTC           string            `json:"created_utc"`
	Algorithm            string            `json:"algorithm"`
	Execution            string            `json:"execution"`
	GoVersion            string            `json:"go_version"`
	GOOS                 string            `json:"goos"`
	GOARCH               string            `json:"goarch"`
	LogicalCPUs          int               `json:"logical_cpus"`
	GOMAXPROCS           int               `json:"gomaxprocs"`
	Fixture              fixtures.Manifest `json:"fixture"`
	Dataset              model.Dataset     `json:"dataset"`
	Config               Config            `json:"config"`
	InputLoadNS          int64             `json:"input_load_ns"`
	CheckerPreparationNS int64             `json:"checker_preparation_ns"`
	MemoryBefore         Memory            `json:"memory_before"`
	MemoryAfter          Memory            `json:"memory_after"`
	ProcessUsage         ProcessUsage      `json:"process_usage"`
	SourceSHA256         string            `json:"runtime_tree_sha256"`
	BuildInfo            string            `json:"build_info"`
	Hardware             string            `json:"hardware"`
	Notes                []string          `json:"notes"`
	Success              bool              `json:"success"`
	Batches              []BatchRun        `json:"batches"`
	ThroughputInterval   *Interval         `json:"throughput_interval,omitempty"`
}

func memory() Memory {
	var m runtime.MemStats
	runtime.ReadMemStats(&m)
	return Memory{m.HeapAlloc, m.TotalAlloc, m.NumGC}
}
func Run(ctx context.Context, b fixtures.Bundle, m fixtures.Manifest, c Config) (r Report, runErr error) {
	r = Report{Errors: []string{}, InputQueries: append([]model.Query{}, b.Queries...), SchemaVersion: model.SchemaVersion, CreatedUTC: time.Now().UTC().Format(time.RFC3339Nano), Algorithm: "tiny_exhaustive_oracle", Execution: "serial_reference_map_not_batched_CSA", GoVersion: runtime.Version(), GOOS: runtime.GOOS, GOARCH: runtime.GOARCH, LogicalCPUs: runtime.NumCPU(), GOMAXPROCS: runtime.GOMAXPROCS(0), Fixture: m, Dataset: b.Dataset, Config: c, Success: false, Batches: []BatchRun{}, Notes: []string{
		"Synthetic infrastructure smoke run; no algorithm performance or real-world quality claim.",
		"Core is the complete oracle call, including input checks and witness reconstruction; it excludes independent validation, objective selection and display ranking.",
		"End-to-end begins at serial per-query execution and includes oracle, validation and final selection/ranking; fixture loading, checker setup and artifact serialization are separate/excluded.",
		"All query requests are processed serially; batch offsets are execution start/completion offsets, not simultaneous submission or queue latency. This is not optimized batch routing.",
		"Batch throughput is successful queries / makespan, never an individual latency estimate; failed queries remain in raw records and query counts.",
		"Runtime heap snapshots are not isolated algorithm memory. Process usage, when available, is cumulative CPU and peak RSS for the whole Go process through measurement completion, excluding artifact serialization.",
		"Power mode, background load, thermals, CPU pinning and cache state are uncontrolled; Go default GC is retained. Inputs are warm after load.",
		"Uniform bootstrap of measured repetition-level throughputs is descriptive only; tiny correlated runs do not establish algorithm superiority.",
	}}
	defer func() {
		if runErr != nil {
			r.Success = false
			r.Errors = append(r.Errors, runErr.Error())
		}
	}()
	if c.Repetitions < 1 || c.Repetitions > 1000 || c.Warmups < 0 || c.Warmups > 100 || c.K <= 0 || c.CandidateCap <= 0 || c.TransferPenalty < 0 || c.TransferPenalty > model.MaxServiceSecond {
		return r, fmt.Errorf("invalid experiment config")
	}
	if len(b.Queries) == 0 {
		return r, fmt.Errorf("empty query set")
	}
	seen := map[string]bool{}
	for _, q := range b.Queries {
		if seen[q.ID] {
			return r, fmt.Errorf("duplicate query ID")
		}
		seen[q.ID] = true
		if err := q.Validate(b.Dataset); err != nil {
			return r, err
		}
	}
	prep := time.Now()
	checker, err := validate.New(b.Dataset)
	if err != nil {
		return r, err
	}
	r.CheckerPreparationNS = time.Since(prep).Nanoseconds()
	r.Success = true
	r.MemoryBefore = memory()
	var firstErr error
	throughputs := []float64{}
	for pass := 0; pass < c.Warmups+c.Repetitions; pass++ {
		batch := BatchRun{Index: pass, Warmup: pass < c.Warmups, Queries: []QueryRun{}}
		start := time.Now()
		for _, q := range b.Queries {
			qr := QueryRun{Query: q, Validated: []model.Validated{}, Final: map[selection.Mode]selection.Result{}, Errors: []string{}}
			begin := time.Now()
			qr.BatchOffsetStartedNS = begin.Sub(start).Nanoseconds()
			core := time.Now()
			qr.Raw, err = oracle.Enumerate(ctx, b.Dataset, q, c.Limits)
			qr.CoreNS = time.Since(core).Nanoseconds()
			if err != nil {
				qr.Errors = append(qr.Errors, err.Error())
			}
			for _, j := range qr.Raw.Journeys {
				v, e := checker.Check(q, j)
				if e != nil {
					qr.Errors = append(qr.Errors, e.Error())
				} else {
					qr.Validated = append(qr.Validated, v)
				}
			}
			if len(qr.Errors) == 0 {
				specs := []selection.Spec{{Mode: selection.Earliest}, {Mode: selection.Pareto, ParetoCriteria: []string{"arrival", "boardings"}}, {Mode: selection.TopK, K: c.K}, {Mode: selection.Candidates, CandidateCap: c.CandidateCap}}
				for _, s := range specs {
					v, e := selection.Select(qr.Validated, qr.Raw.Complete, s)
					if e != nil {
						qr.Errors = append(qr.Errors, e.Error())
					} else {
						qr.Final[s.Mode] = v
					}
				}
				// Apply presentation to the bounded raw candidate set, not to the Pareto set.
				qr.Presentation, err = presentation.Rank(q, qr.Final[selection.Candidates].Journeys, c.K, c.TransferPenalty)
				if err != nil {
					qr.Errors = append(qr.Errors, err.Error())
				}
			}
			end := time.Now()
			qr.EndToEndNS = end.Sub(begin).Nanoseconds()
			qr.BatchOffsetCompletedNS = end.Sub(start).Nanoseconds()
			if len(qr.Errors) > 0 {
				r.Success = false
				if firstErr == nil {
					firstErr = fmt.Errorf("query %s: %s", q.ID, qr.Errors[0])
				}
			} else {
				batch.SuccessfulQueries++
			}
			batch.Queries = append(batch.Queries, qr)
		}
		batch.MakespanNS = time.Since(start).Nanoseconds()
		if batch.MakespanNS > 0 {
			batch.ThroughputQPS = float64(batch.SuccessfulQueries) * 1e9 / float64(batch.MakespanNS)
		}
		r.Batches = append(r.Batches, batch)
		if !batch.Warmup {
			throughputs = append(throughputs, batch.ThroughputQPS)
		}
	}
	r.MemoryAfter = memory()
	r.ProcessUsage = processUsage()
	if len(throughputs) >= 2 && r.Success {
		interval := bootstrap(throughputs, c.Seed)
		r.ThroughputInterval = &interval
	}
	return r, firstErr
}
func bootstrap(samples []float64, seed uint64) Interval {
	const n = 2000
	rng := rand.New(rand.NewPCG(seed, seed^0x9e3779b97f4a7c15))
	means := make([]float64, n)
	var mean float64
	for _, x := range samples {
		mean += x
	}
	mean /= float64(len(samples))
	for i := range means {
		for range samples {
			means[i] += samples[rng.IntN(len(samples))]
		}
		means[i] /= float64(len(samples))
	}
	slices.Sort(means)
	return Interval{Statistic: "mean_batch_throughput_qps", Mean: mean, Lower95: means[49], Upper95: means[1949], Resamples: n, SampleCount: len(samples), Method: "percentile bootstrap; repetition unit; PCG; seed in config; order statistics 50 and 1950 of 2000"}
}
