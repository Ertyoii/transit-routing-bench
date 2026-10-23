package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"github.com/ertyoii/transit-routing-bench/experiment"
	"github.com/ertyoii/transit-routing-bench/fixtures"
	"github.com/ertyoii/transit-routing-go/csa"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/strictjson"
	"github.com/ertyoii/transit-routing-go/validate"
	"os"
	"time"
)

type Case struct {
	ID              string            `json:"id"`
	Query           model.Query       `json:"query"`
	Cap             int               `json:"heuristic_cap"`
	OriginName      string            `json:"origin_name"`
	DestinationName string            `json:"destination_name"`
	Reference       []model.Validated `json:"reference"`
	PreviousQuality json.RawMessage   `json:"previous_quality"`
	PreviousError   string            `json:"previous_error"`
	PreviousStats   json.RawMessage   `json:"previous_stats"`
}

func run() error {
	dataset := flag.String("dataset", "", "normalized dataset")
	input := flag.String("cases", "", "required user-supplied case file")
	out := flag.String("out", "", "new diagnostic artifact")
	exactK := flag.Int("exact-k", 0, "use exact bounded-k compression instead of heuristic cap")
	flag.Parse()
	if *out == "" || *input == "" || *dataset == "" {
		return fmt.Errorf("dataset, cases and output required")
	}
	b, e := os.ReadFile(*dataset)
	if e != nil {
		return e
	}
	var d model.Dataset
	if e = strictjson.Decode(b, &d); e != nil {
		return e
	}
	hash := fixtures.Sum(b)
	b, e = os.ReadFile(*input)
	if e != nil {
		return e
	}
	var cases struct {
		Hash   string `json:"dataset_sha256"`
		Source string `json:"source_manifest"`
		Cases  []Case `json:"cases"`
	}
	if e = strictjson.Decode(b, &cases); e != nil {
		return e
	}
	if cases.Hash != hash {
		return fmt.Errorf("dataset hash mismatch")
	}
	idx, e := csa.New(d)
	if e != nil {
		return e
	}
	checker, e := validate.New(d)
	if e != nil {
		return e
	}
	records := []map[string]any{}
	for _, c := range cases.Cases {
		cfg := csa.Config{MaxLabels: 100000, MaxJourneys: 10000, HeuristicLabelsPerStop: c.Cap}
		if *exactK > 0 {
			cfg.HeuristicLabelsPerStop = 0
			cfg.ExactTopK = *exactK
		}
		for _, v := range c.Reference {
			if e = checker.CheckClaim(c.Query, v); e != nil {
				return e
			}
			cfg.TraceWitnesses = append(cfg.TraceWitnesses, v.Journey)
		}
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		r, err := idx.Single(ctx, c.Query, cfg)
		cancel()
		for _, j := range r.Journeys {
			if _, e = checker.Check(c.Query, j); e != nil {
				return e
			}
		}
		errText := ""
		if err != nil {
			errText = err.Error()
		}
		records = append(records, map[string]any{"case": c, "result": r, "error": errText})
	}
	provenance, e := experiment.Identify(".")
	if e != nil {
		return e
	}
	_, e = experiment.WriteArtifact(*out, map[string]any{"dataset_sha256": hash, "cases_sha256": fixtures.Sum(b), "provenance": provenance, "records": records, "notes": []string{"Trace witnesses observe known reference prefixes only; they do not guide search or pruning. Timings from this instrumented diagnostic are not benchmark timings.", "Preserved caps/limits match paper-comparison-v2. Computational failures retain partial results and cannot prove unreachability."}})
	return e
}
func main() {
	if e := run(); e != nil {
		fmt.Fprintln(os.Stderr, e)
		os.Exit(1)
	}
}
