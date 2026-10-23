package main

import (
	"context"
	"errors"
	"fmt"
	"strings"

	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/tripbased"
	"github.com/ertyoii/transit-routing-go/ultra"
)

// scopedConfig is explicit experiment input. It has no hidden production-sized
// defaults and never derives a looser walking cap from the query roster.
type scopedConfig struct {
	TripBased            *tripbased.Config                           `json:"trip_based,omitempty"`
	Flash                *tripbased.FlashConfig                      `json:"flash,omitempty"`
	Sparse               *ultra.SparseConfig                         `json:"ultra_sparse,omitempty"`
	ULTRA                *ultra.CappedConfig                         `json:"ultra,omitempty"`
	ULTRAQuery           *ultra.Limits                               `json:"ultra_query,omitempty"`
	Patterns             *tripbased.DestinationCappedPatternConfig   `json:"patterns,omitempty"`
	TREX                 *tripbased.TREXConfig                       `json:"trex,omitempty"`
	Verify               *tripbased.TREXStaticCapVerifyLimits        `json:"verification,omitempty"`
	SourceDomainPatterns *tripbased.DestinationSourceDomainConfig    `json:"source_domain_patterns,omitempty"`
	TFixedTransferCap    *int64                                      `json:"trex_fixed_transfer_cap,omitempty"`
	VerifyPreparation    *tripbased.TREXRawVerifierPreparationLimits `json:"verification_preparation,omitempty"`
}

var scopedNames = []string{
	"trip_based_capped",
	"ultra_transfer_complete_capped",
	"ultra_cap_safe_stay_witness_subset_v1",
	"flash_tb_static_stop_pair_suffix_flags_role_caps_v1",
	"tp_destination_fixed_caps_experimental",
	"trex_static_caps_mandatory_verified_experimental",
	tpSourceDomainName,
	trexDefinedProbeName,
}

func isScoped(name string) bool {
	for _, v := range scopedNames {
		if name == v {
			return true
		}
	}
	return false
}

type outcomeError struct {
	outcome string
	cause   error
}

func (e *outcomeError) Error() string { return e.cause.Error() }
func (e *outcomeError) Unwrap() error { return e.cause }

func scopedOutcome(err error) error {
	if err == nil {
		return nil
	}
	if errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded) {
		return err
	}
	s := strings.ToLower(err.Error())
	if strings.Contains(s, "capability:") {
		return &outcomeError{"unsupported_semantics", err}
	}
	if strings.Contains(s, "incomplete") || strings.Contains(s, "budget") || strings.Contains(s, "guard") || strings.Contains(s, "limit reached") {
		return &outcomeError{"incomplete_budget", err}
	}
	return err
}

func trexOutcome(r tripbased.TREXStaticCapResult, err error) error {
	if err == nil {
		if !r.Complete || !r.Certificate.Accepted || !r.VerificationComplete {
			return &outcomeError{"uncertified", fmt.Errorf("mandatory T-REX certificate incomplete")}
		}
		return nil
	}
	if errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded) {
		return err
	}
	switch r.DeclineReason {
	case "unrestricted_representative_infeasible":
		return &outcomeError{"unsupported_cap_certificate", err}
	case "frontier_mismatch":
		return &outcomeError{"correctness_mismatch", err}
	case "verification_incomplete", "ranked_frontier_projection", "reference_frontier_projection":
		// These phases may fail for malformed input as well as work exhaustion.
		// Classify only explicit resource/incomplete errors as budget outcomes.
		var o *outcomeError
		if errors.As(scopedOutcome(err), &o) && o.outcome == "incomplete_budget" {
			return &outcomeError{"incomplete_verification", err}
		}
	case "ranked_search_or_original_resource_guard":
		v := scopedOutcome(err)
		var o *outcomeError
		if errors.As(v, &o) && o.outcome == "incomplete_budget" {
			return &outcomeError{"incomplete_ranked_work", err}
		}
		return v
	}
	return err
}

func prepareScoped(ctx context.Context, d model.Dataset, name string, cfg scopedConfig) (*router, error) {
	r := &router{kind: "pareto", config: cfg}
	present := 0
	for _, v := range []bool{cfg.TripBased != nil, cfg.Flash != nil, cfg.ULTRA != nil, cfg.Sparse != nil, cfg.Patterns != nil, cfg.TREX != nil, cfg.SourceDomainPatterns != nil} {
		if v {
			present++
		}
	}
	if present != 1 {
		return r, fmt.Errorf("scoped config requires exactly one algorithm configuration")
	}
	if err := validateQualificationV2Selection(name, cfg); err != nil {
		return r, err
	}
	if (cfg.ULTRAQuery != nil && cfg.ULTRA == nil && cfg.Sparse == nil) || (cfg.Verify != nil && cfg.TREX == nil) {
		return r, fmt.Errorf("query/verification configuration does not match the selected algorithm")
	}
	if err := validateScopedPreparation(d, cfg); err != nil {
		return r, err
	}
	if name == tpSourceDomainName || name == trexDefinedProbeName {
		return r, prepareQualificationV2(ctx, d, name, cfg, r)
	}
	switch name {
	case "trip_based_capped":
		if cfg.TripBased == nil {
			return r, fmt.Errorf("trip_based configuration required")
		}
		x, err := tripbased.New(ctx, d, *cfg.TripBased)
		if x != nil {
			r.cost = func() any { return x.Preparation() }
		}
		if err != nil {
			return r, scopedOutcome(err)
		}
		r.single = func(c context.Context, q model.Query) rawResult {
			v, e := x.SearchCappedWalking(c, q)
			return rawResult{v.Journeys, v.Complete, v, scopedOutcome(e)}
		}
	case "ultra_transfer_complete_capped":
		if cfg.ULTRA == nil || cfg.ULTRAQuery == nil {
			return r, fmt.Errorf("ultra and ultra_query configurations required")
		}
		x, err := ultra.BuildCapped(ctx, d, *cfg.ULTRA)
		if x != nil {
			r.cost = func() any { return x.Preparation() }
		}
		if err != nil {
			return r, scopedOutcome(err)
		}
		limits := *cfg.ULTRAQuery
		r.single = func(c context.Context, q model.Query) rawResult {
			v, e := x.Search(c, q, limits)
			return rawResult{v.Journeys, v.Complete, v, scopedOutcome(e)}
		}
	case "ultra_cap_safe_stay_witness_subset_v1":
		if cfg.Sparse == nil || cfg.ULTRAQuery == nil {
			return r, fmt.Errorf("ultra_sparse and ultra_query configurations required")
		}
		x, err := ultra.BuildSparse(ctx, d, *cfg.Sparse)
		if x != nil {
			r.cost = func() any { return x.Preparation() }
		}
		if err != nil {
			return r, scopedOutcome(err)
		}
		limits := *cfg.ULTRAQuery
		r.single = func(c context.Context, q model.Query) rawResult {
			v, e := x.Search(c, q, limits)
			return rawResult{v.Journeys, v.Complete, v, scopedOutcome(e)}
		}
	case "flash_tb_static_stop_pair_suffix_flags_role_caps_v1":
		if cfg.Flash == nil {
			return r, fmt.Errorf("flash configuration required")
		}
		if cfg.Flash.Semantics != "static_stop_pair_v1" || cfg.Flash.WalkingPolicy != "query_role_caps_v1" || cfg.Flash.ProfilePolicy != "" || cfg.Flash.RetainedSourceStart != "" {
			return r, fmt.Errorf("named FLASH adapter requires static_stop_pair_v1, query_role_caps_v1 and no retained profile policy")
		}
		x, err := tripbased.BuildFlash(ctx, d, *cfg.Flash)
		if x != nil {
			r.cost = func() any { return x.CostSummary() }
		}
		if err != nil {
			return r, scopedOutcome(err)
		}
		r.single = func(c context.Context, q model.Query) rawResult {
			v, e := x.Search(c, q)
			return rawResult{v.Journeys, v.Complete, v, scopedOutcome(e)}
		}
	case "tp_destination_fixed_caps_experimental":
		if cfg.Patterns == nil {
			return r, fmt.Errorf("patterns configuration required")
		}
		x, err := tripbased.BuildDestinationCappedPatterns(ctx, d, *cfg.Patterns)
		if x != nil {
			r.cost = func() any { return x.CostSummary() }
		}
		if err != nil {
			return r, scopedOutcome(err)
		}
		if !x.Complete() {
			return r, &outcomeError{"incomplete_budget", fmt.Errorf("fixed-cap TP preparation incomplete")}
		}
		r.single = func(c context.Context, q model.Query) rawResult {
			v, e := x.Search(c, q)
			return rawResult{v.Journeys, v.Complete, v, scopedOutcome(e)}
		}
	case "trex_static_caps_mandatory_verified_experimental":
		if cfg.TREX == nil || cfg.Verify == nil {
			return r, fmt.Errorf("trex and positive mandatory verification configurations required")
		}
		x, err := tripbased.BuildTREXStaticRulesCandidate(ctx, d, *cfg.TREX)
		if x != nil {
			r.cost = func() any { return x.Diagnostic() }
		}
		if err != nil {
			return r, scopedOutcome(err)
		}
		certificate, err := tripbased.PrepareTREXStaticCapCertificate(ctx, x, *cfg.Verify)
		if err != nil {
			return r, scopedOutcome(err)
		}
		r.single = func(c context.Context, q model.Query) rawResult {
			v, e := certificate.Search(c, q)
			e = trexOutcome(v, e)
			return rawResult{v.Journeys, v.Complete && e == nil, v, e}
		}
	default:
		return r, fmt.Errorf("unknown scoped algorithm %s", name)
	}
	return r, nil
}
