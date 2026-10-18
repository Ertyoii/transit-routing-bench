package experiment_test

import (
	"context"
	"github.com/ertyoii/transit-routing-bench/experiment"
	"github.com/ertyoii/transit-routing-bench/fixtures"
	"github.com/ertyoii/transit-routing-bench/oracle"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/selection"
	"testing"
)

func TestArtifactRetainsRawFinalTimingAndFailure(t *testing.T) {
	b, m, e := fixtures.Load("../testdata/tiny.manifest.json")
	if e != nil {
		t.Fatal(e)
	}
	cfg := experiment.Config{Repetitions: 2, Warmups: 1, Seed: 20261017, K: 3, CandidateCap: 10, TransferPenalty: 300, Limits: oracle.Limits{MaxStates: 100000, MaxJourneys: 10000}}
	r, e := experiment.Run(context.Background(), b, m, cfg)
	if e != nil || !r.Success {
		t.Fatalf("run failed: %v", e)
	}
	if len(r.Batches) != 3 || !r.Batches[0].Warmup || r.ThroughputInterval == nil || r.ThroughputInterval.SampleCount != 2 {
		t.Fatal("repetitions/warmups/interval missing")
	}
	for _, batch := range r.Batches {
		if len(batch.Queries) != 5 || batch.SuccessfulQueries != 5 || batch.MakespanNS <= 0 || batch.ThroughputQPS <= 0 {
			t.Fatal("batch measurements missing")
		}
		for _, q := range batch.Queries {
			if !q.Raw.Complete || q.CoreNS <= 0 || q.EndToEndNS < q.CoreNS || q.BatchOffsetCompletedNS < q.BatchOffsetStartedNS || len(q.Final) != 4 {
				t.Fatalf("query details missing: %+v", q)
			}
		}
	}
	cfg.Limits.MaxStates = 1
	r, e = experiment.Run(context.Background(), b, m, cfg)
	if e == nil || r.Success || r.ThroughputInterval != nil {
		t.Fatal("truncation presented as successful benchmark")
	}
	q := r.Batches[0].Queries[0]
	if q.Raw.Complete || len(q.Errors) == 0 {
		t.Fatal("incomplete raw status lost")
	}
	if _, ok := q.Final[selection.TopK]; ok {
		t.Fatal("exact final output supplied after truncation")
	}
}

func TestPreflightErrorsCannotReportSuccess(t *testing.T) {
	b, m, e := fixtures.Load("../testdata/tiny.manifest.json")
	if e != nil {
		t.Fatal(e)
	}
	config := experiment.Config{Repetitions: 1, K: 3, CandidateCap: 10, Limits: oracle.Limits{MaxStates: 100, MaxJourneys: 100}}
	for _, kind := range []string{"config", "empty", "duplicate", "endpoint", "dataset"} {
		t.Run(kind, func(t *testing.T) {
			input := b
			input.Queries = append([]model.Query{}, b.Queries...)
			cfg := config
			switch kind {
			case "config":
				cfg.Repetitions = 0
			case "empty":
				input.Queries = nil
			case "duplicate":
				input.Queries = append(input.Queries, input.Queries[0])
			case "endpoint":
				input.Queries[0].Origin = "absent"
			case "dataset":
				input.Dataset.SchemaVersion = "unsupported"
			}
			r, e := experiment.Run(context.Background(), input, m, cfg)
			if e == nil || r.Success || len(r.Errors) == 0 || len(r.InputQueries) != len(input.Queries) {
				t.Fatalf("preflight report contradicts error or loses workload: %+v %v", r, e)
			}
		})
	}
}
