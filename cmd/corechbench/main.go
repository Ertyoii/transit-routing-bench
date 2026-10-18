// corechbench records an exact transfer-graph experiment, not an ULTRA transit benchmark.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"math/rand/v2"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"time"

	"github.com/ertyoii/transit-routing-bench/evaluation"
	"github.com/ertyoii/transit-routing-bench/experiment"
	"github.com/ertyoii/transit-routing-bench/fixtures"
	"github.com/ertyoii/transit-routing-go/corech"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/strictjson"
)

type record struct {
	Raw            corech.Row    `json:"raw"`
	Final          []corech.Path `json:"final"`
	Complete       bool          `json:"complete"`
	Error          string        `json:"error,omitempty"`
	CoreNS         int64         `json:"core_ns"`
	ResponseNS     int64         `json:"response_ns"`
	AllocatedBytes uint64        `json:"core_allocated_bytes"`
}
type pass struct {
	Algorithm  string   `json:"algorithm"`
	Repetition int      `json:"repetition"`
	Warmup     bool     `json:"warmup"`
	Records    []record `json:"records"`
}
type summary struct {
	Algorithm                string                  `json:"algorithm"`
	Repetition               int                     `json:"repetition"`
	Warmup                   bool                    `json:"warmup"`
	File                     string                  `json:"file"`
	SHA256                   string                  `json:"sha256"`
	Rows                     int                     `json:"rows"`
	Cells                    int                     `json:"cells"`
	Errors                   int                     `json:"errors"`
	MakespanNS               int64                   `json:"makespan_ns"`
	SuccessfulRowsPerSecond  float64                 `json:"successful_rows_per_second"`
	SuccessfulCellsPerSecond float64                 `json:"successful_cells_per_second"`
	Core                     evaluation.Distribution `json:"whole_row_core_ns"`
	Response                 evaluation.Distribution `json:"whole_row_response_ns"`
	AllocatedBytes           uint64                  `json:"core_allocated_bytes"`
}

func read(p string, v any, strict bool) (string, error) {
	b, e := os.ReadFile(p)
	if e != nil {
		return "", e
	}
	if strict {
		e = strictjson.Decode(b, v)
	} else {
		e = json.Unmarshal(b, v)
	}
	return fixtures.Sum(b), e
}

// This validator follows supplied original-edge IDs and consults independently
// audited expected distances. It does not use the contraction or search code.
func validate(r corech.Row, raw map[string]model.Footpath, want map[string]map[string]int64) error {
	if !r.Complete {
		return fmt.Errorf("incomplete row: %s", r.Error)
	}
	for _, p := range r.Paths {
		cost, found := want[r.Source][p.Target]
		if r.Source == p.Target {
			cost, found = 0, true
		}
		if p.Found != found || found && p.Duration != cost {
			return fmt.Errorf("audited distance differs: %s -> %s: got %v/%d want %v/%d", r.Source, p.Target, p.Found, p.Duration, found, cost)
		}
		if !found {
			if len(p.RawEdges) > 0 || len(p.CoreArcs) > 0 {
				return fmt.Errorf("unreachable cell has path")
			}
			continue
		}
		at, sum := r.Source, int64(0)
		for _, id := range p.RawEdges {
			e, ok := raw[id]
			if !ok || e.From != at {
				return fmt.Errorf("invalid raw witness edge %q", id)
			}
			at = e.To
			sum += e.Duration
		}
		if at != p.Target || sum != p.Duration || sum > r.MaximumDuration {
			return fmt.Errorf("raw witness endpoint/duration mismatch")
		}
	}
	return nil
}
func run() error {
	dp := flag.String("dataset", "artifacts/raw-walk-repair/frozen/dataset-raw.json", "frozen raw graph dataset")
	bp := flag.String("base", "artifacts/heldout-monday-evening/dataset.json", "original stop list")
	cp := flag.String("closures", "artifacts/osm-central128-v2/closures.json", "independently audited expected distances")
	out := flag.String("out-dir", "", "new output directory")
	reps := flag.Int("repetitions", 3, "measured repetitions")
	warmups := flag.Int("warmups", 1, "retained warmups")
	prepTimeout := flag.Duration("prep-timeout", 180*time.Second, "cooperative preparation deadline")
	timeout := flag.Duration("timeout", 5*time.Second, "whole row core deadline")
	localWitness := flag.Int("witness-settled", 128, "per-search conservative witness limit")
	globalSettled := flag.Int("max-witness-settled", 30000000, "global witness settled limit; exhaustion fails")
	globalEdges := flag.Int("max-witness-edges", 150000000, "global witness edge limit; exhaustion fails")
	maxDegree := flag.Float64("maximum-average-core-out-degree", 14, "natural partial contraction stop")
	hardware := flag.String("hardware", "unrecorded", "verified hardware description")
	flag.Parse()
	if *out == "" || *reps < 1 || *warmups < 0 || *prepTimeout <= 0 || *timeout <= 0 {
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
		return fmt.Errorf("build with scripts/build.sh")
	}
	started := time.Now()
	var d, base model.Dataset
	var closures struct {
		Anchors []struct {
			Stop string `json:"stop"`
		} `json:"anchors"`
		Closures []struct {
			From     string `json:"from"`
			To       string `json:"to"`
			Duration int64  `json:"duration"`
		} `json:"closures"`
	}
	dh, e := read(*dp, &d, true)
	if e != nil {
		return e
	}
	bh, e := read(*bp, &base, true)
	if e != nil {
		return e
	}
	ch, e := read(*cp, &closures, false)
	if e != nil {
		return e
	}
	if dh != "c84c7b38258f456f7bf82b3cf3201a7c8e3aab42d8828f64d1c67e478da6397e" || bh != "188f979c805e60ce96a0da4addd909c22925b0ba515e432ac6099a8f385a5bc7" || ch != "10b7f036ab11d2d313b09121257163e76b6d35e6f6fa7559986cb08ea4693e14" {
		return fmt.Errorf("frozen input hashes differ")
	}
	loadNS := time.Since(started).Nanoseconds()
	started = time.Now()
	vertices, protected, anchors := []string{}, []string{}, []string{}
	for _, s := range d.Stops {
		vertices = append(vertices, s.ID)
	}
	for _, s := range base.Stops {
		protected = append(protected, s.ID)
	}
	for _, a := range closures.Anchors {
		anchors = append(anchors, a.Stop)
	}
	sort.Strings(anchors)
	raw := map[string]model.Footpath{}
	for _, e := range d.Footpaths {
		raw[e.ID] = e
	}
	want := map[string]map[string]int64{}
	for _, a := range anchors {
		want[a] = map[string]int64{}
	}
	for _, c := range closures.Closures {
		want[c.From][c.To] = c.Duration
	}
	checkerNS := time.Since(started).Nanoseconds()
	cfg := corech.Config{TargetCoreVertices: len(protected), MaximumAverageCoreOutDegree: *maxDegree, WitnessSettledPerSearch: *localWitness, MaxContractions: 1000000, MaxArcs: 3000000, MaxWitnessSettled: *globalSettled, MaxWitnessEdges: *globalEdges}
	limits := corech.QueryLimits{MaxSettled: 1000000, MaxEdges: 5000000, MaxUnpackedEdges: 1000000}
	prep := map[string]any{}
	indices := map[string]*corech.Index{}
	for _, name := range []string{"identity", "core_ch"} {
		c := cfg
		if name == "identity" {
			c.TargetCoreVertices = len(vertices)
		}
		runtime.GC()
		before := experiment.SnapshotResources()
		t := time.Now()
		ctx, cancel := context.WithTimeout(context.Background(), *prepTimeout)
		x, buildErr := corech.Build(ctx, vertices, d.Footpaths, protected, c)
		elapsed := time.Since(t).Nanoseconds()
		cancel()
		after := experiment.SnapshotResources()
		gcStart := time.Now()
		runtime.GC()
		gcNS := time.Since(gcStart).Nanoseconds()
		retained := experiment.SnapshotResources()
		snapshotStart := time.Now()
		snap := x.Snapshot()
		copyNS := time.Since(snapshotStart).Nanoseconds()
		io, writeErr := experiment.WriteArtifact(filepath.Join(*out, name+"-index.json"), snap)
		if writeErr != nil {
			return writeErr
		}
		msg := ""
		if buildErr != nil {
			msg = buildErr.Error()
		}
		ok := buildErr == nil && elapsed <= prepTimeout.Nanoseconds()
		prep[name] = map[string]any{"complete": ok, "error": msg, "elapsed_ns": elapsed, "allocated_bytes": after.Memory.TotalAllocBytes - before.Memory.TotalAllocBytes, "before": before, "after": after, "post_gc": retained, "post_gc_ns": gcNS, "post_gc_heap_delta_bytes": int64(retained.Memory.HeapAllocBytes) - int64(before.Memory.HeapAllocBytes), "snapshot_copy_ns": copyNS, "index_io": io, "stats": x.Stats(), "config": c}
		if _, e = experiment.WriteArtifact(filepath.Join(*out, name+"-preparation.json"), prep[name]); e != nil {
			return e
		}
		fmt.Printf("%s preparation complete=%v elapsed=%.3fs core=%d edges=%d shortcuts=%d\n", name, ok, float64(elapsed)/1e9, x.Stats().CoreVertices, x.Stats().CoreEdges, x.Stats().Shortcuts)
		if !ok {
			_, writeErr = experiment.WriteArtifact(filepath.Join(*out, "summary.json"), map[string]any{"success": false, "phase": "preparation", "provenance": prov, "dataset_sha256": dh, "preparation": prep, "error": msg, "requested_rows_per_pass": len(anchors), "requested_cells_per_pass": len(anchors) * len(anchors), "resources": experiment.SnapshotResources()})
			if writeErr != nil {
				return writeErr
			}
			return fmt.Errorf("preparation incomplete; saved diagnostics")
		}
		indices[name] = x
	}
	measure := func(name, source string, targets []string, deadline time.Duration) record {
		ctx, cancel := context.WithTimeout(context.Background(), deadline)
		defer cancel()
		var before, after runtime.MemStats
		runtime.ReadMemStats(&before)
		t := time.Now()
		r, err := indices[name].SearchMany(ctx, source, targets, 1200, limits)
		coreNS := time.Since(t).Nanoseconds()
		runtime.ReadMemStats(&after)
		if err == nil && coreNS > deadline.Nanoseconds() {
			err = fmt.Errorf("cooperative deadline exceeded")
		}
		responseStart := time.Now()
		if err == nil {
			err = validate(r, raw, want)
		}
		responseNS := coreNS + time.Since(responseStart).Nanoseconds()
		rec := record{Raw: r, Final: []corech.Path{}, Complete: err == nil, CoreNS: coreNS, ResponseNS: responseNS, AllocatedBytes: after.TotalAlloc - before.TotalAlloc}
		if err != nil {
			rec.Error = err.Error()
		} else {
			rec.Final = r.Paths
		}
		return rec
	}
	summaries := []summary{}
	allOK := true
	throughputs := map[string][]float64{}
	const seed uint64 = 20261018
	for rep := 0; rep < *warmups+*reps; rep++ {
		sources := append([]string{}, anchors...)
		targets := append([]string{}, anchors...)
		rng := rand.New(rand.NewPCG(seed, uint64(rep)))
		rng.Shuffle(len(sources), func(i, j int) { sources[i], sources[j] = sources[j], sources[i] })
		rng.Shuffle(len(targets), func(i, j int) { targets[i], targets[j] = targets[j], targets[i] })
		names := []string{"identity", "core_ch"}
		if rep%2 == 1 {
			names[0], names[1] = names[1], names[0]
		}
		for _, name := range names {
			p := pass{Algorithm: name, Repetition: rep, Warmup: rep < *warmups, Records: []record{}}
			coreTimes, responseTimes := []float64{}, []float64{}
			allocated := uint64(0)
			errors := 0
			start := time.Now()
			for _, source := range sources {
				r := measure(name, source, targets, *timeout)
				p.Records = append(p.Records, r)
				coreTimes = append(coreTimes, float64(r.CoreNS))
				responseTimes = append(responseTimes, float64(r.ResponseNS))
				allocated += r.AllocatedBytes
				if !r.Complete {
					errors++
				}
			}
			makespan := time.Since(start).Nanoseconds()
			file := fmt.Sprintf("%s-pass-%02d.json", name, rep)
			io, e := experiment.WriteArtifact(filepath.Join(*out, file), p)
			if e != nil {
				return e
			}
			s := summary{Algorithm: name, Repetition: rep, Warmup: p.Warmup, File: file, SHA256: io.SHA256, Rows: len(sources), Cells: len(sources) * len(targets), Errors: errors, MakespanNS: makespan, SuccessfulRowsPerSecond: float64(len(sources)-errors) * 1e9 / float64(makespan), SuccessfulCellsPerSecond: float64((len(sources)-errors)*len(targets)) * 1e9 / float64(makespan), Core: evaluation.Summarize(coreTimes), Response: evaluation.Summarize(responseTimes), AllocatedBytes: allocated}
			summaries = append(summaries, s)
			if errors != 0 {
				allOK = false
			}
			if !p.Warmup {
				throughputs[name] = append(throughputs[name], s.SuccessfulRowsPerSecond)
			}
			fmt.Printf("%s pass=%d rows=%d errors=%d makespan=%.3fs\n", name, rep, len(sources), errors, float64(makespan)/1e9)
		}
	}
	// Diagnostic partitions and forced deadlines retain every requested cell.
	partitions := []any{}
	deadlines := []any{}
	for _, name := range []string{"identity", "core_ch"} {
		for i, source := range anchors {
			failed := measure(name, source, anchors, time.Nanosecond)
			if failed.Complete {
				allOK = false
			}
			deadlines = append(deadlines, map[string]any{"algorithm": name, "record": failed})
			if i < 8 {
				for start := 0; start < len(anchors); start += 17 {
					ts := anchors[start:min(start+17, len(anchors))]
					r := measure(name, source, ts, *timeout)
					if !r.Complete {
						allOK = false
					}
					partitions = append(partitions, map[string]any{"algorithm": name, "record": r})
				}
			}
		}
	}
	if _, e = experiment.WriteArtifact(filepath.Join(*out, "target-partitions.json"), partitions); e != nil {
		return e
	}
	if _, e = experiment.WriteArtifact(filepath.Join(*out, "forced-deadlines.json"), deadlines); e != nil {
		return e
	}
	failedCfg := cfg
	failedCfg.MaxContractions = 1
	start := time.Now()
	ctx, cancel := context.WithTimeout(context.Background(), *prepTimeout)
	failed, fe := corech.Build(ctx, vertices, d.Footpaths, protected, failedCfg)
	cancel()
	failedNS := time.Since(start).Nanoseconds()
	rejected, re := failed.SearchMany(context.Background(), anchors[0], anchors, 1200, limits)
	failureOK := fe != nil && !failed.Complete() && re != nil && !rejected.Complete
	allOK = allOK && failureOK
	if _, e = experiment.WriteArtifact(filepath.Join(*out, "forced-preparation.json"), map[string]any{"expected_failure_observed": failureOK, "elapsed_ns": failedNS, "snapshot": failed.Snapshot(), "attempted_query": rejected}); e != nil {
		return e
	}
	cis := map[string]experiment.Interval{}
	if *reps >= 2 {
		for _, name := range []string{"identity", "core_ch"} {
			ci, e := experiment.ThroughputConfidence(throughputs[name], seed)
			if e != nil {
				return e
			}
			ci.Statistic = "whole_row_throughput_rows_per_second"
			cis[name] = ci
		}
	}
	_, e = experiment.WriteArtifact(filepath.Join(*out, "summary.json"), map[string]any{"success": allOK, "created_utc": time.Now().UTC().Format(time.RFC3339Nano), "provenance": prov, "dataset_sha256": dh, "base_sha256": bh, "closures_sha256": ch, "anchors": anchors, "protected_vertices": len(protected), "seed": seed, "hardware": *hardware, "go_version": runtime.Version(), "goos": runtime.GOOS, "goarch": runtime.GOARCH, "logical_cpus": runtime.NumCPU(), "gomaxprocs": runtime.GOMAXPROCS(0), "repetitions": *reps, "warmups": *warmups, "input_load_ns": loadNS, "checker_preparation_ns": checkerNS, "preparation": prep, "query_limits": limits, "query_timeout_ns": timeout.Nanoseconds(), "preparation_timeout_ns": prepTimeout.Nanoseconds(), "passes": summaries, "throughput_intervals": cis, "resources_final": experiment.SnapshotResources(), "scope": []string{"Exact ordinary walking duration only. Core-to-core one-to-many row includes path unpacking. No transit algorithm or ULTRA shortcut preprocessing claim.", "Each row has 128 target cells. Row latency is never divided by target count. Core excludes independent original-edge validation; response adds it. Pass makespan includes per-row memory instrumentation and record collection, excludes result serialization. Core allocation measurements exclude validator allocations.", "Identity graph uses same search routine as performance control, not correctness oracle. Expected distances come from independently audited raw OSM closure metric; all original paths checked.", "Post-GC heap differences are process-level approximations, not isolated ownership sizes. Snapshot copying/serialization separate. Confidence intervals resample three repetition units when repetitions=3 and are weak descriptive estimates.", "Unknown accessibility and unverified stop connectors remain. This does not validate an exact Singapore timetable or authorize regional expansion."}})
	if e != nil {
		return e
	}
	if !allOK {
		return fmt.Errorf("one or more checks failed; all records retained")
	}
	return nil
}
func main() {
	if e := run(); e != nil {
		fmt.Fprintln(os.Stderr, e)
		os.Exit(1)
	}
}
