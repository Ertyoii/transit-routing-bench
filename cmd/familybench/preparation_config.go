package main

import (
	"fmt"

	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/tripbased"
	"github.com/ertyoii/transit-routing-go/ultra"
)

// Validate settings whose owning constructor may inspect them only after an
// earlier resource decline. This is configuration validation, not preprocessing
// or a replacement for the library's dataset/capability checks. Keep these
// exposed configuration requirements aligned with the pinned vendor contract.
func validateScopedPreparation(d model.Dataset, c scopedConfig) error {
	if c.Flash != nil {
		if err := validateFlashPreparation(d, *c.Flash); err != nil {
			return err
		}
	}
	if c.Patterns != nil {
		if err := validateFlashPreparation(d, c.Patterns.Patterns.Profile); err != nil {
			return err
		}
	}
	if c.ULTRAQuery != nil {
		l := *c.ULTRAQuery
		if !positiveULTRALimits(l) {
			return fmt.Errorf("positive ULTRA query limits required")
		}
	}
	if c.Verify != nil && (c.Verify.MaxStates <= 0 || c.Verify.MaxJourneys <= 0 || c.Verify.MaxScans <= 0) {
		return fmt.Errorf("positive verification limits required")
	}
	if c.TREX != nil && len(c.TREX.Partition) > 0 {
		p := c.TREX.Partition
		if c.TREX.Levels < 0 || c.TREX.Levels > 12 {
			return fmt.Errorf("invalid T-REX partition levels")
		}
		if len(p) != len(d.Stops) {
			return fmt.Errorf("invalid T-REX partition: must cover exactly all stops")
		}
		used := make([]bool, 1<<uint(c.TREX.Levels))
		for _, s := range d.Stops {
			leaf, ok := p[s.ID]
			if !ok || leaf < 0 || leaf >= len(used) {
				return fmt.Errorf("invalid T-REX partition leaf")
			}
			used[leaf] = true
		}
		for _, present := range used {
			if !present {
				return fmt.Errorf("invalid T-REX partition: empty leaf")
			}
		}
		// Endpoints in the same leaf imply their entire weak walking component
		// is unsplit; no routing or partition-construction logic is shared here.
		for _, edge := range d.Footpaths {
			if p[edge.From] != p[edge.To] {
				return fmt.Errorf("invalid T-REX partition: cuts a walking component")
			}
		}
	}
	return nil
}

func positiveULTRALimits(l ultra.Limits) bool {
	return l.MaxRuns > 0 && l.MaxConnectionVisits > 0 && l.MaxWalkSettled > 0 && l.MaxWalkEdges > 0 && l.MaxShortcuts > 0 && l.MaxOutputLegs > 0
}

func validateFlashPreparation(d model.Dataset, c tripbased.FlashConfig) error {
	l := c.Limits
	if c.Cells < 1 || c.Cells > len(d.Stops) || c.MaxBoardings < 1 || c.MaxBoardings > 32 || l.MaxStops < 1 || l.MaxTrips < 1 || l.MaxClosurePaths < 1 || l.MaxWalkSettled < 1 || l.MaxTransfers < 1 || l.MaxRuns < 1 || l.MaxWork < 1 || l.MaxFlagBytes < 1 || l.MaxWitnesses < 1 || l.MaxQuerySegments < 1 {
		return fmt.Errorf("invalid FLASH preparation configuration: positive configuration/budgets required")
	}
	if c.Semantics == "static_stop_pair_v1" && (l.MaxSuffixBytes <= 0 || l.MaxSnapshotTransfers <= 0) {
		return fmt.Errorf("invalid FLASH preparation configuration: positive suffix-state byte and snapshot-record budgets required")
	}
	return nil
}
