package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"github.com/ertyoii/transit-routing-bench/experiment"
	"github.com/ertyoii/transit-routing-bench/fixtures"
	"github.com/ertyoii/transit-routing-go/gtfs"
	"os"
)

func run() error {
	zip := flag.String("zip", "", "local public GTFS ZIP")
	expected := flag.String("sha256", "", "required expected raw SHA-256")
	date := flag.String("date", "2026-10-16", "service-date anchor")
	start := flag.Int64("start", 25200, "snapshot start service second")
	end := flag.Int64("end", 32400, "snapshot end service second")
	policy := flag.String("frequency-policy", "reject", "reject or deterministic_model")
	kind := flag.String("data-kind", "scheduled_snapshot", "scheduled_snapshot or modeled_snapshot")
	edges := flag.String("transfer-edges", "none", "none or minimum_time_proxy")
	max := flag.Int("max-connections", 1000000, "fail rather than truncate")
	out := flag.String("out", "", "new dataset JSON")
	report := flag.String("report", "", "new audit JSON")
	flag.Parse()
	if *expected == "" || *out == "" || *report == "" {
		return fmt.Errorf("sha256, out and report are required")
	}
	info, e := os.Stat(*zip)
	if e != nil {
		return e
	}
	if info.Size() > 64<<20 {
		return fmt.Errorf("compressed ZIP exceeds 64 MiB profile")
	}
	data, e := os.ReadFile(*zip)
	if e != nil {
		return e
	}
	if fixtures.Sum(data) != *expected {
		return fmt.Errorf("raw SHA-256 mismatch")
	}
	provenance, e := experiment.Identify(".")
	if e != nil {
		return e
	}
	d, a, e := gtfs.Import(data, gtfs.Options{ServiceDate: *date, Start: *start, End: *end, FrequencyPolicy: *policy, DataKind: *kind, TransferEdges: *edges, MaxConnections: *max})
	if e != nil {
		return e
	}
	for _, entry := range []struct {
		path  string
		value any
	}{{*out, d}, {*report, struct {
		gtfs.Audit
		Provenance experiment.Provenance `json:"provenance"`
	}{a, provenance}}} {
		f, e := os.OpenFile(entry.path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
		if e != nil {
			return e
		}
		enc := json.NewEncoder(f)
		e = enc.Encode(entry.value)
		closeErr := f.Close()
		if e != nil {
			return e
		}
		if closeErr != nil {
			return closeErr
		}
	}
	fmt.Printf("Imported %d instances, %d connections; %s\n", a.InstanceCount, a.ConnectionCount, *kind)
	return nil
}
func main() {
	if e := run(); e != nil {
		fmt.Fprintln(os.Stderr, e)
		os.Exit(1)
	}
}
