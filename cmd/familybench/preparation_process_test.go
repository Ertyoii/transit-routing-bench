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
		{"partial-tp", "tp_destination_fixed_caps_experimental", "tp-partial", "incomplete_budget", "source guard", true},
		{"preparation-deadline", "trip_based_capped", "tb", "deadline", "deadline", true},
		{"unsupported-capability", "trex_static_caps_mandatory_verified_experimental", "trex", "unsupported_semantics", "capability:", true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			dir := t.TempDir()
			out := filepath.Join(dir, "results")
			args := []string{"-fixture", "testdata/scoped.manifest.json", "-algorithm", tc.algorithm,
				"-out-dir", out, "-warmups", "0", "-repetitions", "1", "-batch-size", "3"}
			if tc.config != "" {
				config := filepath.Join("testdata/scoped-config", tc.config+".json")
				if tc.config == "invalid" {
					value := scopedInput(t, "tb")
					value.TripBased.MaxTransfers = 0
					config = filepath.Join(dir, "invalid.json")
					writeProcessInput(t, config, value)
				}
				args = append(args, "-scoped-config", config)
			}
			if tc.name == "preparation-deadline" {
				args = append(args, "-prep-timeout", "1ns")
			}
			if tc.name == "unsupported-capability" {
				bundle := scopedFixture(t)
				// A valid type-0 recommendation is outside this constructor's
				// declared static type-2/type-3 profile, not malformed input.
				bundle.Dataset.Transfers = append(bundle.Dataset.Transfers, model.TransferRule{ID: "recommended", FromStop: "O", ToStop: "A", Type: 0})
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
					Complete bool            `json:"complete"`
					Status   string          `json:"status"`
					Error    string          `json:"error"`
					Cost     json.RawMessage `json:"index_cost_summary"`
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
			if exit != wantExit || summary.Success != tc.wantSuccess || summary.Preparation.Complete || summary.Preparation.Status != tc.status || !strings.Contains(summary.Preparation.Error, tc.cause) {
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
