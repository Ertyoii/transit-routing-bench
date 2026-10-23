package main

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/ertyoii/transit-routing-bench/fixtures"
	"github.com/ertyoii/transit-routing-go/model"
)

// Exercise the process boundary: testing a constructor or status helper alone
// cannot catch a slot's not-run status masking a fatal preparation error.
func TestPreparationProcessOutcomes(t *testing.T) {
	root, err := filepath.Abs("../..")
	if err != nil {
		t.Fatal(err)
	}
	env := append(os.Environ(), "GOTOOLCHAIN=local", "GOWORK=off", "GOPROXY=off", "GOSUMDB=off", "GOMAXPROCS=2")
	binary := filepath.Join(t.TempDir(), "familybench")
	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	defer cancel()
	build := exec.CommandContext(ctx, "sh", "scripts/build.sh", "familybench", binary)
	build.Dir, build.Env = root, env
	if output, err := build.CombinedOutput(); err != nil {
		t.Fatalf("source-bound CLI build: %v\n%s", err, output)
	}
	for _, tc := range []struct {
		name, algorithm, config, status, cause string
		wantSuccess                            bool
	}{
		{"unknown-adapter", "deliberately_unknown", "", "routing_error", "unknown algorithm", false},
		{"misleading-adapter-name", "capability: incomplete: budget exhausted", "", "routing_error", "unknown algorithm", false},
		{"mismatched-config", "trip_based_capped", "flash", "routing_error", "trip_based configuration required", false},
		{"invalid-budget-config", "trip_based_capped", "invalid", "routing_error", "invalid preparation/budget configuration", false},

		{"tp-zero-stops", "tp_destination_fixed_caps_experimental", "tp-zero-stops", "routing_error", "invalid FLASH preparation configuration", false},
		{"tp-negative-stops", "tp_destination_fixed_caps_experimental", "tp-negative-stops", "routing_error", "invalid FLASH preparation configuration", false},
		{"tp-zero-trips", "tp_destination_fixed_caps_experimental", "tp-zero-trips", "routing_error", "invalid FLASH preparation configuration", false},
		{"tp-negative-trips", "tp_destination_fixed_caps_experimental", "tp-negative-trips", "routing_error", "invalid FLASH preparation configuration", false},
		{"tp-masked-flash-budget", "tp_destination_fixed_caps_experimental", "tp-masked-flash-budget", "routing_error", "invalid FLASH preparation configuration", false},
		{"flash-masked-suffix", "flash_tb_static_stop_pair_suffix_flags_role_caps_v1", "flash-masked-suffix", "routing_error", "invalid FLASH preparation configuration", false},
		{"flash-masked-snapshot", "flash_tb_static_stop_pair_suffix_flags_role_caps_v1", "flash-masked-snapshot", "routing_error", "invalid FLASH preparation configuration", false},
		{"trex-partition-coverage", "trex_static_caps_mandatory_verified_experimental", "trex-partition-coverage", "routing_error", "invalid T-REX partition", false},
		{"trex-partition-leaf", "trex_static_caps_mandatory_verified_experimental", "trex-partition-leaf", "routing_error", "invalid T-REX partition", false},
		{"trex-masked-partition", "trex_static_caps_mandatory_verified_experimental", "trex-masked-partition", "routing_error", "invalid T-REX partition", false},
		{"trex-masked-verification", "trex_static_caps_mandatory_verified_experimental", "trex-masked-verification", "routing_error", "positive verification limits required", false},
		{"ultra-invalid-query", "ultra_transfer_complete_capped", "ultra-invalid-query", "routing_error", "positive ULTRA query limits required", false},
		{"ultra-masked-query", "ultra_transfer_complete_capped", "ultra-masked-query", "routing_error", "positive ULTRA query limits required", false},
		{"subset-masked-query", "ultra_cap_safe_stay_witness_subset_v1", "subset-masked-query", "routing_error", "positive ULTRA query limits required", false},
		{"legacy-masked-budget", "transfer_patterns", "", "routing_error", "positive preparation/query flags required", false},
		{"tp-network-budget", "tp_destination_fixed_caps_experimental", "tp-network-budget", "incomplete_budget", "network size guard", true},
		{"flash-network-budget", "flash_tb_static_stop_pair_suffix_flags_role_caps_v1", "flash-network-budget", "incomplete_budget", "network size budget", true},
		{"trex-network-budget", "trex_static_caps_mandatory_verified_experimental", "trex-network-budget", "incomplete_budget", "size", true},
		{"ultra-preparation-budget", "ultra_transfer_complete_capped", "ultra-preparation-budget", "incomplete_budget", "budget", true},
		{"partial-tp", "tp_destination_fixed_caps_experimental", "tp-partial", "incomplete_budget", "source guard", true},
		{"preparation-deadline", "trip_based_capped", "tb", "deadline", "deadline", true},
		{"capability-with-diagnostic-id", "raptor", "", "unsupported_semantics", "unknown_invalid", true},
		{"unsupported-capability", "trex_static_caps_mandatory_verified_experimental", "trex", "unsupported_semantics", "capability:", true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			dir := t.TempDir()
			out := filepath.Join(dir, "results")
			args := []string{"-fixture", "testdata/scoped.manifest.json", "-algorithm", tc.algorithm,
				"-out-dir", out, "-warmups", "0", "-repetitions", "1", "-batch-size", "3"}
			if tc.config != "" {
				config := filepath.Join("testdata/scoped-config", tc.config+".json")
				if strings.Contains(tc.config, "-") && tc.config != "tp-partial" {
					config = filepath.Join(dir, "configuration.json")
					writeProcessInput(t, config, stagedPreparationInput(t, tc.config))
				}
				if tc.config == "invalid" {
					value := scopedInput(t, "tb")
					value.TripBased.MaxTransfers = 0
					config = filepath.Join(dir, "invalid.json")
					writeProcessInput(t, config, value)
				}
				args = append(args, "-scoped-config", config)
			}
			if tc.name == "legacy-masked-budget" {
				args = append(args, "-max-work", "1", "-max-transfers", "0")
			}
			if tc.name == "preparation-deadline" {
				args = append(args, "-prep-timeout", "1ns")
			}
			if tc.name == "unsupported-capability" || tc.name == "capability-with-diagnostic-id" {
				bundle := scopedFixture(t)
				// A valid type-0 recommendation is outside this constructor's
				// declared static type-2/type-3 profile, not malformed input.
				if tc.name == "unsupported-capability" {
					bundle.Dataset.Transfers = append(bundle.Dataset.Transfers, model.TransferRule{ID: "recommended", FromStop: "O", ToStop: "A", Type: 0})
				} else {
					// Zero-duration service is valid model input outside paper's
					// positive-time profile. Its ID is data, not an error class.
					bundle.Dataset.Connections[0].ID = "unknown_invalid"
					bundle.Dataset.Connections[0].Arrival = bundle.Dataset.Connections[0].Departure
				}
				dataset, queries := filepath.Join(dir, "data.json"), filepath.Join(dir, "queries.json")
				data := writeProcessInput(t, dataset, bundle.Dataset)
				items := []map[string]any{}
				for _, q := range bundle.Queries {
					items = append(items, map[string]any{"stratum": "synthetic", "query": q})
				}
				writeProcessInput(t, queries, map[string]any{"seed": 7, "method": "original-synthetic", "dataset_sha256": fixtures.Sum(data), "items": items})
				args = append([]string{"-dataset", dataset, "-queries", queries}, args[2:]...)
			}
			cmd := exec.CommandContext(ctx, binary, args...)
			cmd.Dir, cmd.Env = root, env
			output, runErr := cmd.CombinedOutput()
			exit := 0
			if runErr != nil {
				var exited *exec.ExitError
				if !errors.As(runErr, &exited) {
					t.Fatalf("CLI could not run: %v\n%s", runErr, output)
				}
				exit = exited.ExitCode()
			}
			var summary struct {
				Success     bool `json:"success"`
				Preparation struct {
					Complete     bool            `json:"complete"`
					ExpectedSkip bool            `json:"expected_skip"`
					ProcessFatal bool            `json:"process_fatal"`
					Status       string          `json:"status"`
					Error        string          `json:"error"`
					Cost         json.RawMessage `json:"index_cost_summary"`
				} `json:"preparation"`
				Passes []struct {
					Requested int            `json:"requested"`
					Attempted int            `json:"attempted"`
					NotRun    int            `json:"not_run"`
					Complete  int            `json:"complete"`
					Statuses  map[string]int `json:"statuses"`
				} `json:"passes"`
			}
			readProcessOutput(t, filepath.Join(out, "summary.json"), &summary)
			wantExit := 1
			if tc.wantSuccess {
				wantExit = 0
			}
			if exit != wantExit || summary.Success != tc.wantSuccess || summary.Preparation.Complete || summary.Preparation.ExpectedSkip != tc.wantSuccess || summary.Preparation.ProcessFatal == tc.wantSuccess || summary.Preparation.Status != tc.status || !strings.Contains(summary.Preparation.Error, tc.cause) {
				t.Errorf("process outcome: exit=%d success=%v preparation=%+v; want exit=%d success=%v status=%s\n%s", exit, summary.Success, summary.Preparation, wantExit, tc.wantSuccess, tc.status, output)
			}
			if len(summary.Passes) != 2 {
				t.Fatalf("ordinary and forced passes must remain retained: %+v", summary.Passes)
			}
			for _, pass := range summary.Passes {
				if pass.Requested != 3 || pass.Attempted != 0 || pass.NotRun != 3 || pass.Complete != 0 || len(pass.Statuses) != 1 || pass.Statuses["not_run_preparation_unavailable"] != 3 {
					t.Fatal("not-run denominators changed", pass)
				}
			}
			for _, name := range []string{"pass-00.json", "forced-deadline.json"} {
				var artifact struct {
					Records []struct {
						Query      model.Query       `json:"query"`
						Attempted  *bool             `json:"attempted"`
						Completed  *bool             `json:"completed"`
						ValidEmpty *bool             `json:"valid_empty"`
						Transit    *bool             `json:"transit"`
						Status     string            `json:"status"`
						Error      string            `json:"error"`
						Raw        []json.RawMessage `json:"raw"`
						Final      []json.RawMessage `json:"final"`
					} `json:"records"`
				}
				readProcessOutput(t, filepath.Join(out, name), &artifact)
				ids := map[string]bool{}
				for _, row := range artifact.Records {
					if row.Query.ID == "" || ids[row.Query.ID] || row.Status != "not_run_preparation_unavailable" || !strings.Contains(row.Error, tc.cause) || row.Raw == nil || row.Final == nil || len(row.Raw) != 0 || len(row.Final) != 0 {
						t.Fatal("lost or misclassified not-run witness row", row)
					}
					ids[row.Query.ID] = true
					for _, flag := range []*bool{row.Attempted, row.Completed, row.ValidEmpty, row.Transit} {
						if flag == nil || *flag {
							t.Fatal("not-run row acquired completion/empty/transit status", row)
						}
					}
				}
				if len(ids) != 3 {
					t.Fatal("query identities lost", ids)
				}
			}
			if tc.name == "partial-tp" {
				var cost struct {
					Complete bool `json:"complete"`
					Stats    struct {
						SourcesCompleted int `json:"sources_completed"`
					} `json:"stats"`
				}
				if err := json.Unmarshal(summary.Preparation.Cost, &cost); err != nil || cost.Complete || cost.Stats.SourcesCompleted != 1 {
					t.Fatal("expected partial TP work was not retained", string(summary.Preparation.Cost), err)
				}
			}
		})
	}
}

func writeProcessInput(t *testing.T, path string, value any) []byte {
	t.Helper()
	data, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, data, 0600); err != nil {
		t.Fatal(err)
	}
	return data
}

func readProcessOutput(t *testing.T, path string, value any) {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(data, value); err != nil {
		t.Fatal(err)
	}
}

// Supply malformed nested configuration alongside a valid tight construction
// budget: the process must reject configuration before accepting a resource skip.
func stagedPreparationInput(t *testing.T, name string) scopedConfig {
	t.Helper()
	base := strings.Split(name, "-")[0]
	if base == "subset" {
		base = "ultra-subset"
	}
	if base == "ultra" {
		base = "ultra-control"
	}
	v := scopedInput(t, base)
	switch name {
	case "tp-zero-stops":
		v.Patterns.Patterns.Profile.Limits.MaxStops = 0
	case "tp-negative-stops":
		v.Patterns.Patterns.Profile.Limits.MaxStops = -1
	case "tp-zero-trips":
		v.Patterns.Patterns.Profile.Limits.MaxTrips = 0
	case "tp-negative-trips":
		v.Patterns.Patterns.Profile.Limits.MaxTrips = -1
	case "tp-masked-flash-budget":
		v.Patterns.Patterns.Profile.Limits.MaxStops = 1
		v.Patterns.Patterns.Profile.Limits.MaxTransfers = 0
	case "flash-masked-suffix":
		v.Flash.Limits.MaxStops = 1
		v.Flash.Limits.MaxSuffixBytes = 0
	case "flash-masked-snapshot":
		v.Flash.Limits.MaxStops = 1
		v.Flash.Limits.MaxSnapshotTransfers = 0
	case "trex-partition-coverage", "trex-masked-partition":
		v.TREX.Partition = map[string]int{"O": -1}
		if name == "trex-masked-partition" {
			v.TREX.Limits.MaxStops = 1
		}
	case "trex-partition-leaf":
		v.TREX.Partition = map[string]int{}
		for _, s := range scopedFixture(t).Dataset.Stops {
			v.TREX.Partition[s.ID] = 0
		}
		v.TREX.Partition["O"] = -1
	case "trex-masked-verification":
		v.TREX.Limits.MaxStops = 1
		v.Verify.MaxStates = 0
	case "ultra-invalid-query", "ultra-masked-query":
		v.ULTRAQuery.MaxRuns = 0
		if name == "ultra-masked-query" {
			v.ULTRA.Limits.MaxRuns = 1
		}
	case "subset-masked-query":
		v.ULTRAQuery.MaxOutputLegs = -1
		v.Sparse.Capped.Limits.MaxRuns = 1
	case "tp-network-budget":
		v.Patterns.Patterns.Profile.Limits.MaxStops = 1
	case "flash-network-budget":
		v.Flash.Limits.MaxStops = 1
	case "trex-network-budget":
		v.TREX.Limits.MaxStops = 1
	case "ultra-preparation-budget":
		v.ULTRA.Limits.MaxRuns = 1
	default:
		t.Fatalf("unknown staged preparation input %s", name)
	}
	return v
}
