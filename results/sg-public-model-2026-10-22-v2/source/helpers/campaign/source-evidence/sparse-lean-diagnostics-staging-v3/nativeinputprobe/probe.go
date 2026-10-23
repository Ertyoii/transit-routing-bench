// Package nativeinputprobe reports only strict parsing/binding on the actual
// consuming driver path. It constructs no routing, checking or quality index.
package nativeinputprobe

import (
	"encoding/json"
	"fmt"
	"github.com/ertyoii/transit-routing-bench/experiment"
	"github.com/ertyoii/transit-routing-bench/workloadseed"
	"os"
)

func Emit(driver, schema, datasetHash, queriesHash, configHash string, seed workloadseed.Seed, count int, selection any) error {
	p, e := experiment.Identify(".")
	if e != nil {
		return e
	}
	if !p.RuntimeMatchesBuild {
		return fmt.Errorf("input-only requires source-bound build")
	}
	return json.NewEncoder(os.Stdout).Encode(map[string]any{"event": "input_only_acceptance", "accepted": true, "driver": driver, "schema": schema, "dataset_sha256": datasetHash, "queries_sha256": queriesHash, "scoped_configuration_sha256": configHash, "seed_metadata": seed.Metadata(), "query_count": count, "selection": selection, "argv": os.Args[1:], "provenance": p, "scope": "actual_consuming_driver_parser_only_no_router_constructor_no_search_no_quality_no_outcomes"})
}
