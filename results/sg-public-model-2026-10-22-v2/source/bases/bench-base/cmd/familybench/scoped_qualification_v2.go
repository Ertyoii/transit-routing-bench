package main

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/tripbased"
)

const tpSourceDomainName = "tp_source_domain_retained_fixed_caps_experimental_v1"
const trexDefinedProbeName = "trex_fixed_transfer_cap_ranked_defined_probe_verified_experimental_v1"

// New policy fields cannot silently change the meaning of a legacy adapter.
func validateQualificationV2Selection(name string, c scopedConfig) error {
	if c.SourceDomainPatterns != nil && name != tpSourceDomainName {
		return fmt.Errorf("source_domain_patterns requires %s", tpSourceDomainName)
	}
	if (c.TFixedTransferCap != nil || c.VerifyPreparation != nil) && name != trexDefinedProbeName {
		return fmt.Errorf("fixed transfer cap and verifier preparation require %s", trexDefinedProbeName)
	}
	if name == tpSourceDomainName && c.SourceDomainPatterns == nil {
		return fmt.Errorf("source_domain_patterns configuration required")
	}
	if name == trexDefinedProbeName && (c.TREX == nil || c.Verify == nil || c.TFixedTransferCap == nil || c.VerifyPreparation == nil) {
		return fmt.Errorf("trex, verification, trex_fixed_transfer_cap and verification_preparation configurations required")
	}
	return nil
}

func prepareQualificationV2(ctx context.Context, d model.Dataset, name string, c scopedConfig, r *router) error {
	switch name {
	case tpSourceDomainName:
		x, err := tripbased.BuildDestinationSourceDomainPatterns(ctx, d, *c.SourceDomainPatterns)
		if x != nil {
			r.cost = func() any { return x.CostSummary() }
		}
		if err != nil {
			return scopedOutcome(err)
		}
		if !x.DomainComplete() || x.GlobalComplete() {
			return fmt.Errorf("source-domain TP completion certificate invalid")
		}
		r.single = func(ctx context.Context, q model.Query) rawResult {
			v, err := x.Search(ctx, q)
			return rawResult{v.Journeys, v.Complete, v, scopedOutcome(err)}
		}
		return nil
	case trexDefinedProbeName:
		x, err := tripbased.BuildTREXFixedTransferCapRankedCandidate(ctx, d, *c.TREX, *c.TFixedTransferCap)
		var rawPreparation tripbased.TREXRawVerifierPreparationStats
		var certificatePreparationNS int64
		prepared := false
		r.cost = func() any {
			var ranked any
			if x != nil {
				ranked = x.Diagnostic()
			}
			return struct {
				Ranked                   any                                       `json:"ranked_index"`
				RawVerifierPreparation   tripbased.TREXRawVerifierPreparationStats `json:"raw_verifier_preparation"`
				CertificatePreparationNS int64                                     `json:"certificate_preparation_ns"`
				CertificatePrepared      bool                                      `json:"certificate_prepared"`
			}{ranked, rawPreparation, certificatePreparationNS, prepared}
		}
		if err != nil {
			return scopedOutcome(err)
		}
		start := time.Now()
		certificate, stats, err := tripbased.PrepareTREXFixedTransferCapCandidate(ctx, x, *c.Verify, *c.VerifyPreparation)
		certificatePreparationNS, rawPreparation = time.Since(start).Nanoseconds(), stats
		if err != nil {
			return fixedTREXPreparationOutcome(err)
		}
		prepared = true
		r.single = func(ctx context.Context, q model.Query) rawResult {
			v, err := certificate.Search(ctx, q)
			err = fixedTREXOutcome(v, err)
			if err != nil {
				v.Journeys = []model.Journey{}
				v.Complete, v.Certificate.Accepted, v.Error = false, false, err.Error()
			}
			return rawResult{v.Journeys, v.Complete, v, err}
		}
		return nil
	default:
		return fmt.Errorf("unknown qualification adapter %s", name)
	}
}

func fixedTREXPreparationOutcome(err error) error {
	// These exact owner errors describe exhausted positive raw preparation
	// limits. Wrap them in the existing process classifier's resource contract;
	// malformed or unfamiliar errors remain process-fatal.
	switch err.Error() {
	case "oracle inconclusive: enumeration limit reached: preparation rows",
		"oracle inconclusive: enumeration limit reached: preparation work",
		"oracle inconclusive: enumeration limit reached: preparation payload":
		return fmt.Errorf("T-REX incomplete: raw verifier preparation budget exhausted: %w", err)
	default:
		return scopedOutcome(err)
	}
}

func fixedTREXOutcome(v tripbased.TREXFixedTransferCapCandidateResult, err error) error {
	if err == nil {
		if !v.Complete || !v.Certificate.Accepted || !v.VerificationComplete {
			return &outcomeError{"uncertified", fmt.Errorf("mandatory fixed-transfer-cap T-REX certificate incomplete")}
		}
		return nil
	}
	if errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded) {
		return err
	}
	switch v.DeclineReason {
	case "frontier_mismatch":
		return &outcomeError{"correctness_mismatch", err}
	case "fixed_transfer_cap_mismatch":
		return &outcomeError{"unsupported_semantics", err}
	case "ranked_candidate_infeasible":
		return &outcomeError{"unsupported_cap_certificate", err}
	case "ranked_search_incomplete", "replay_work_incomplete":
		return &outcomeError{"incomplete_ranked_work", err}
	case "ranked_search_or_original_resource_guard":
		classified := scopedOutcome(err)
		var o *outcomeError
		if errors.As(classified, &o) && o.outcome == "incomplete_budget" {
			return &outcomeError{"incomplete_ranked_work", err}
		}
		return classified
	case "verification_incomplete", "ranked_frontier_projection", "reference_frontier_projection":
		var o *outcomeError
		if errors.As(scopedOutcome(err), &o) && o.outcome == "incomplete_budget" {
			return &outcomeError{"incomplete_verification", err}
		}
	}
	return scopedOutcome(err)
}
