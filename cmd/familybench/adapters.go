package main

import (
	"context"
	"fmt"
	"github.com/ertyoii/transit-routing-go/csa"
	"github.com/ertyoii/transit-routing-go/eacsa"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/raptor"
	"github.com/ertyoii/transit-routing-go/tripbased"
)

type rawResult struct {
	Journeys []model.Journey
	Complete bool
	Detail   any
	Err      error
}
type router struct {
	single func(context.Context, model.Query) rawResult
	shared func(context.Context, []model.Query) ([]rawResult, any)
	config any
	cost   func() any
	kind   string
}

var names = []string{"csa_arrival_single", "csa_arrival_shared", "csa_score_single", "csa_score_shared", "ea_csa_layered", "raptor", "mc_raptor", "trip_based", "flash_tb", "transfer_patterns", "scalable_tp", "trex", "raptor_early", "mc_raptor_early"}

func prepare(ctx context.Context, d model.Dataset, name string, k, maxLabels, maxTransfers, maxWork, maxWitnesses int) (*router, error) {
	r := &router{kind: "pareto"}
	// Validate exposed flags before any constructor can decline on a tighter
	// resource guard. A decline must not hide malformed later-stage settings.
	usesLabels := name == "mc_raptor" || name == "mc_raptor_early" || name == "csa_arrival_single" || name == "csa_arrival_shared" || name == "csa_score_single" || name == "csa_score_shared"
	usesTransfers := name == "trip_based" || name == "flash_tb" || name == "transfer_patterns" || name == "scalable_tp" || name == "trex"
	usesWork := usesTransfers && name != "trip_based" || name == "mc_raptor" || name == "mc_raptor_early"
	if usesLabels && maxLabels <= 0 || usesTransfers && maxTransfers <= 0 || usesWork && maxWork <= 0 {
		return r, fmt.Errorf("positive preparation/query flags required")
	}
	cc := csa.Config{ExactTopK: k, MaxLabels: maxLabels, MaxJourneys: k}
	fc := tripbased.FlashConfig{Cells: 8, MaxBoardings: 4, Limits: tripbased.FlashLimits{MaxStops: 10000, MaxTrips: 100000, MaxClosurePaths: 1000000, MaxWalkSettled: 2000000, MaxTransfers: maxTransfers, MaxRuns: 200000, MaxWork: maxWork, MaxFlagBytes: 100000000, MaxWitnesses: maxWitnesses, MaxQuerySegments: 1000000}}
	pc := tripbased.PatternConfig{Profile: fc, MaxPatterns: 2000000, MaxNodes: 4000000, MaxEdges: 6000000, MaxDirectEntries: 5000000, MaxBuildWork: maxWork, MaxQueryWork: 2000000, MaxQueryLabels: 1000000}
	switch name {
	case "csa_arrival_single", "csa_arrival_shared", "csa_score_single", "csa_score_shared":
		x, e := csa.New(d)
		if e != nil {
			return r, e
		}
		r.config = cc
		r.kind = "arrival_top_k"
		caps := name == "csa_score_single" || name == "csa_score_shared"
		if caps {
			r.kind = "score_top_k"
		}
		r.single = func(c context.Context, q model.Query) rawResult {
			var v csa.Result
			var e error
			if caps {
				v, e = x.StratifiedSingle(c, q, cc)
			} else {
				v, e = x.Single(c, q, cc)
			}
			complete := v.TopKComplete
			if caps {
				complete = v.CapComplete
			}
			return rawResult{v.Journeys, complete, v, e}
		}
		if name == "csa_arrival_shared" || name == "csa_score_shared" {
			r.shared = func(c context.Context, qs []model.Query) ([]rawResult, any) {
				var v csa.Batch
				var e error
				if caps {
					v, e = x.StratifiedShared(c, qs, cc)
				} else {
					v, e = x.Shared(c, qs, cc)
				}
				out := []rawResult{}
				for _, q := range qs {
					out = append(out, rawResult{Err: fmt.Errorf("missing CSA lane %s: %v", q.ID, e)})
				}
				for i, lane := range v.Results {
					if i >= len(out) {
						break
					}
					var le error
					if lane.Error != "" {
						le = fmt.Errorf("%s", lane.Error)
					}
					complete := lane.TopKComplete
					if caps {
						complete = lane.CapComplete
					}
					out[i] = rawResult{lane.Journeys, complete, lane, le}
				}
				lanes := 0
				for _, q := range qs {
					if caps {
						lanes += q.MaxBoardings + 1
					} else {
						lanes++
					}
				}
				return out, map[string]any{"shared_connection_visits": v.SharedConnectionVisits, "native_batch_makespan_ns": v.MakespanNS, "expanded_lanes": lanes, "shared_error": fmt.Sprint(e)}
			}
		}
	case "ea_csa_layered":
		x, e := eacsa.New(d)
		if e != nil {
			return r, e
		}
		r.config = x.Capabilities()
		r.single = func(c context.Context, q model.Query) rawResult {
			v, e := x.Search(c, q)
			return rawResult{v.Journeys, v.Complete, v.Stats, e}
		}
	case "raptor", "raptor_early":
		x, e := raptor.New(d)
		if e != nil {
			return r, e
		}
		r.config = x.Capabilities()
		r.single = func(c context.Context, q model.Query) rawResult {
			if name == "raptor_early" {
				v, stats, e := x.SearchEarlyPruning(c, q)
				return rawResult{v.Journeys, v.Complete, map[string]any{"router": v.Stats, "early_pruning": stats}, e}
			}
			v, e := x.Search(c, q)
			return rawResult{v.Journeys, v.Complete, v.Stats, e}
		}
	case "mc_raptor", "mc_raptor_early":
		x, e := raptor.New(d)
		if e != nil {
			return r, e
		}
		cfg := raptor.MultiConfig{Criterion: "walking_seconds", MaxLabels: maxLabels, MaxConnectionVisits: maxWork, EarlyPruning: name == "mc_raptor_early"}
		r.kind = "pareto_walking"
		r.config = cfg
		r.single = func(c context.Context, q model.Query) rawResult {
			v, e := x.SearchMulti(c, q, cfg)
			return rawResult{v.Journeys, v.Complete, v, e}
		}
	case "trip_based":
		cfg := tripbased.Config{TransferWalkingLimit: 900, MaxTransfers: maxTransfers, MaxQueuedSegments: 1000000}
		r.config = cfg
		x, e := tripbased.New(ctx, d, cfg)
		if x != nil {
			r.cost = func() any { return x.Preparation() }
		}
		if e != nil {
			return r, e
		}
		r.single = func(c context.Context, q model.Query) rawResult {
			v, e := x.Search(c, q)
			return rawResult{v.Journeys, v.Complete, v.Stats, e}
		}
	case "flash_tb":
		r.config = fc
		x, e := tripbased.BuildFlash(ctx, d, fc)
		r.cost = func() any { return x.CostSummary() }
		if e != nil {
			return r, e
		}
		r.single = func(c context.Context, q model.Query) rawResult {
			v, e := x.Search(c, q)
			return rawResult{v.Journeys, v.Complete, v.Stats, e}
		}
	case "transfer_patterns":
		pc.Profile.Cells = 1
		r.config = pc
		x, e := tripbased.BuildPatterns(ctx, d, pc)
		r.cost = func() any { return x.CostSummary() }
		if e != nil {
			return r, e
		}
		r.single = func(c context.Context, q model.Query) rawResult {
			v, e := x.Search(c, q)
			return rawResult{v.Journeys, v.Complete, v, e}
		}
	case "scalable_tp":
		pc.Profile.Cells = 1
		sc := tripbased.ScalableConfig{Patterns: pc, MaxClusterSize: 32, MaxDirectArcs: 1000000, MaxProfileRuns: 200000, MaxProfileLabels: 1000000, DirectIndex: "demand", MaxDirectPairs: 1000000, BorderStorage: "cluster", MaxClusterDAGs: 100000, BorderSearchMode: "border", MaxLocalCacheEntries: 100000, BorderMergeMaxSize: 128, BorderReductionPercent: 25}
		r.config = sc
		x, e := tripbased.BuildScalable(ctx, d, sc)
		r.cost = func() any { return x.CostSummary() }
		if e != nil {
			return r, e
		}
		r.single = func(c context.Context, q model.Query) rawResult {
			v, e := x.Search(c, q)
			return rawResult{v.Journeys, v.Complete, v, e}
		}
	case "trex":
		cfg := tripbased.TREXConfig{Levels: 3, MaxBoardings: 4, Limits: tripbased.TREXLimits{MaxStops: 10000, MaxTrips: 100000, MaxInputEdges: 1000000, MaxClosurePaths: 1000000, MaxWalkSettled: 2000000, MaxTransfers: maxTransfers, MaxRuns: 200000, MaxWork: maxWork, MaxWitnesses: maxWitnesses, MaxOverlayEntries: 20000000, MaxQueuedSegments: 1000000, MaxQueryWork: 2000000}}
		r.config = cfg
		x, e := tripbased.BuildTREX(ctx, d, cfg)
		r.cost = func() any { return x.CostSummary() }
		if e != nil {
			return r, e
		}
		r.single = func(c context.Context, q model.Query) rawResult {
			v, e := x.Search(c, q)
			return rawResult{v.Journeys, v.Complete, v.Stats, e}
		}
	default:
		return r, fmt.Errorf("unknown algorithm %s", name)
	}
	return r, nil
}
