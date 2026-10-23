package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"github.com/ertyoii/transit-routing-bench/experiment"
	"github.com/ertyoii/transit-routing-bench/fixtures"
	"github.com/ertyoii/transit-routing-bench/oracle"
	"os"
	"runtime/debug"
	"time"
)

func run() error {
	manifest := flag.String("fixture", "testdata/tiny.manifest.json", "pinned synthetic manifest")
	output := flag.String("out", "", "output JSON path; exclusive creation; stdout when empty")
	root := flag.String("source-dir", ".", "source directory for Go source hash")
	hardware := flag.String("hardware", "unrecorded", "verified CPU, RAM and OS description, no device identifiers")
	repeats := flag.Int("repetitions", 5, "measured oracle smoke passes")
	warmup := flag.Int("warmups", 1, "retained warmup passes")
	seed := flag.Uint64("seed", 20261017, "PCG bootstrap seed")
	k := flag.Int("k", 3, "strict EA-order k and presentation k (separate outputs)")
	cap := flag.Int("candidate-cap", 10, "independent candidate cap before display ranking")
	penalty := flag.Int64("ranking-transfer-penalty", 300, "ranking-only seconds per transfer; never a boarding buffer")
	states := flag.Int("max-states", 100000, "oracle expansion budget; exhaustion fails")
	journeys := flag.Int("max-journeys", 10000, "oracle output budget; exhaustion fails")
	flag.Parse()
	load := time.Now()
	b, m, err := fixtures.Load(*manifest)
	if err != nil {
		return err
	}
	loadNS := time.Since(load).Nanoseconds()
	provenance, err := experiment.Identify(*root)
	if err != nil {
		return err
	}
	cfg := experiment.Config{Repetitions: *repeats, Warmups: *warmup, Seed: *seed, K: *k, CandidateCap: *cap, TransferPenalty: *penalty, Limits: oracle.Limits{MaxStates: *states, MaxJourneys: *journeys}}
	report, runErr := experiment.Run(context.Background(), b, m, cfg)
	report.InputLoadNS = loadNS
	report.SourceSHA256 = provenance.RuntimeTreeSHA256
	report.Provenance = provenance
	report.Hardware = *hardware
	if info, ok := debug.ReadBuildInfo(); ok {
		report.BuildInfo = info.String()
	}
	if runErr != nil {
		report.Success = false
	}
	if *output != "" {
		if _, err = experiment.WriteArtifact(*output, report); err != nil {
			return err
		}
	} else {
		encoder := json.NewEncoder(os.Stdout)
		encoder.SetIndent("", "  ")
		if err = encoder.Encode(report); err != nil {
			return err
		}
	}
	if runErr != nil {
		return runErr
	}
	return nil
}
func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
