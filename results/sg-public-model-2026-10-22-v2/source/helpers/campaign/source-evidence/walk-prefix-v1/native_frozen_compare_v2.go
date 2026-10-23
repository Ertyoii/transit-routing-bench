// Walking-prefix public differential: deterministic storage counters retained.
// Only nondeterministic phase/level clock and allocation samples are removed.
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/tripbased"
	"os"
)

type fixture struct {
	Name      string         `json:"name"`
	Dataset   model.Dataset  `json:"dataset"`
	Query     model.Query    `json:"query"`
	Level     int            `json:"level"`
	Levels    int            `json:"levels"`
	Partition map[string]int `json:"partition"`
}

func read(path string, dst any) {
	b, e := os.ReadFile(path)
	if e != nil {
		panic(e)
	}
	if e = json.Unmarshal(b, dst); e != nil {
		panic(e)
	}
}
func canonical(v any) any {
	b, e := json.Marshal(v)
	if e != nil {
		panic(e)
	}
	var out map[string]any
	if e = json.Unmarshal(b, &out); e != nil {
		panic(e)
	}
	delete(out, "phases")
	if st, ok := out["stats"].(map[string]any); ok {
		if levels, ok := st["levels"].([]any); ok {
			for _, row := range levels {
				if level, ok := row.(map[string]any); ok {
					delete(level, "elapsed_ns")
					delete(level, "allocated_bytes")
				}
			}
		}
	}
	return out
}
func errtext(e error) string {
	if e != nil {
		return e.Error()
	}
	return ""
}
func main() {
	var rows []fixture
	read("tripbased/testdata/exact_storage_cases.json", &rows)
	for _, file := range []string{"tripbased/testdata/trex_preprocessing/fixtures.json", "tripbased/testdata/trex_cap_certification/fixtures.json"} {
		var doc struct {
			Fixtures []fixture `json:"fixtures"`
		}
		read(file, &doc)
		rows = append(rows, doc.Fixtures...)
	}
	var fixed fixture
	read("tripbased/testdata/trex_fixed_transfer_cap/rank-loss.json", &fixed)
	fixed.Levels = 1
	rows = append(rows, fixed)
	enc := json.NewEncoder(os.Stdout)
	for i, r := range rows {
		for _, exact := range []bool{false, true} {
			for _, fixed := range []bool{false, true} {
				level := r.Level
				if r.Levels > level {
					level = r.Levels
				}
				if len(r.Partition) > 0 && level == 0 {
					level = 1
				}
				cfg := tripbased.TREXConfig{ExactStorage: exact, Levels: level, MaxBoardings: 4, Partition: r.Partition, Limits: tripbased.TREXLimits{MaxStops: 100, MaxTrips: 100, MaxInputEdges: 1000, MaxClosurePaths: 10000, MaxWalkSettled: 10000, MaxTransfers: 20000, MaxRuns: 10000, MaxWork: 2000000, MaxWitnesses: 10000, MaxOverlayEntries: 100000, MaxQueuedSegments: 100000, MaxQueryWork: 1000000}}
				ctx := context.Background()
				var x *tripbased.TREXIndex
				var e error
				if fixed {
					cap := int64(600)
					if r.Query.Walking != nil {
						cap = r.Query.Walking.Transfer
					}
					x, e = tripbased.BuildTREXFixedTransferCapRankedCandidate(ctx, r.Dataset, cfg, cap)
				} else {
					x, e = tripbased.BuildTREXStaticRulesCandidate(ctx, r.Dataset, cfg)
				}
				out := map[string]any{"case": i, "name": r.Name, "exact": exact, "fixed": fixed, "build_error": errtext(e), "snapshot": canonical(x.Snapshot())}
				if e == nil {
					a, ae := x.Search(ctx, r.Query)
					b, be := x.SearchRanked(ctx, r.Query)
					c, ce := x.SearchUnranked(ctx, r.Query)
					out["overlay"] = a
					out["overlay_error"] = errtext(ae)
					out["ranked"] = b
					out["ranked_error"] = errtext(be)
					out["unranked"] = c
					out["unranked_error"] = errtext(ce)
					limits := tripbased.TREXStaticCapVerifyLimits{MaxStates: 200000, MaxJourneys: 20000, MaxScans: 4000000}
					if fixed {
						gate, stats, ge := tripbased.PrepareTREXFixedTransferCapCandidate(ctx, x, limits, tripbased.TREXRawVerifierPreparationLimits{MaxRows: 10000, MaxWork: 100000, MaxPayloadBytes: 10000000})
						out["prepare_stats"] = stats
						out["prepare_error"] = errtext(ge)
						if ge == nil {
							v, ve := gate.Search(ctx, r.Query)
							out["certified"] = v
							out["certified_error"] = errtext(ve)
						}
					} else {
						gate, ge := tripbased.PrepareTREXStaticCapCertificate(ctx, x, limits)
						out["prepare_error"] = errtext(ge)
						if ge == nil {
							v, ve := gate.Search(ctx, r.Query)
							out["certified"] = v
							out["certified_error"] = errtext(ve)
						}
					}
				}
				if e := enc.Encode(out); e != nil {
					panic(e)
				}
			}
		}
	}
	fmt.Fprintf(os.Stderr, "compared cases=%d storage/build variants=%d\n", len(rows), len(rows)*4)
}
