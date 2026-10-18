// legproof records bounded raw-walking leg certificates independently of routing time.
package main

import (
	"context"
	"flag"
	"fmt"
	"github.com/ertyoii/transit-routing-bench/experiment"
	"github.com/ertyoii/transit-routing-bench/fixtures"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/paper"
	"github.com/ertyoii/transit-routing-go/strictjson"
	"os"
	"runtime"
	"time"
)

func run() error {
	dp := flag.String("dataset", "", "normalized snapshot")
	qp := flag.String("queries", "", "frozen workload")
	out := flag.String("out", "", "new result file")
	deadline := flag.Duration("timeout", 5*time.Second, "per-proof cooperative deadline")
	flag.Parse()
	if *dp == "" || *qp == "" || *out == "" {
		return fmt.Errorf("dataset, queries and output required")
	}
	db, e := os.ReadFile(*dp)
	if e != nil {
		return e
	}
	qb, e := os.ReadFile(*qp)
	if e != nil {
		return e
	}
	var d model.Dataset
	var w struct {
		Seed          uint64 `json:"seed"`
		Method        string `json:"method"`
		DatasetSHA256 string `json:"dataset_sha256"`
		Items         []struct {
			Stratum string      `json:"stratum"`
			Query   model.Query `json:"query"`
		} `json:"items"`
	}
	if e = strictjson.Decode(db, &d); e != nil {
		return e
	}
	if e = strictjson.Decode(qb, &w); e != nil {
		return e
	}
	if w.DatasetSHA256 != fixtures.Sum(db) {
		return fmt.Errorf("dataset hash mismatch")
	}
	prov, e := experiment.Identify(".")
	if e != nil {
		return e
	}
	start := time.Now()
	p, e := paper.New(d)
	if e != nil {
		return e
	}
	prep := time.Since(start).Nanoseconds()
	rows := []any{}
	all := true
	for _, i := range w.Items {
		ctx, cancel := context.WithTimeout(context.Background(), *deadline)
		start := time.Now()
		r, e := p.CertifyLegBound(ctx, i.Query, paper.DefaultProofLimits())
		elapsed := time.Since(start).Nanoseconds()
		cancel()
		message := ""
		if e != nil {
			message = e.Error()
		}
		cert := e == nil && r.SufficientLegs <= i.Query.MaxLegs && elapsed <= deadline.Nanoseconds()
		all = all && cert
		rows = append(rows, map[string]any{"query": i.Query, "stratum": i.Stratum, "proof": r, "certified": cert, "error": message, "elapsed_ns": elapsed})
	}
	_, e = experiment.WriteArtifact(*out, map[string]any{"success": all, "dataset_sha256": fixtures.Sum(db), "queries_sha256": fixtures.Sum(qb), "provenance": prov, "go_version": runtime.Version(), "proof_limits": paper.DefaultProofLimits(), "timeout_ns": deadline.Nanoseconds(), "profile_preparation_ns": prep, "records": rows, "resources_final": experiment.SnapshotResources(), "scope": "Leg-resource preflight only, not a route optimum; routing cores separately repeat certification and include its cost."})
	if e != nil {
		return e
	}
	if !all {
		return fmt.Errorf("one or more leg resources remain uncertified; full records saved")
	}
	return nil
}
func main() {
	if e := run(); e != nil {
		fmt.Fprintln(os.Stderr, e)
		os.Exit(1)
	}
}
