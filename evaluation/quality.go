// Package evaluation compares independently validated objective values. It does
// not decide itinerary feasibility and never treats an incomplete pool as truth.
package evaluation

import (
	"fmt"
	"github.com/ertyoii/transit-routing-go/model"
	"sort"
)

type Gap struct {
	Reference *int64 `json:"reference_seconds"`
	Observed  *int64 `json:"observed_seconds"`
	Missing   bool   `json:"missing"`
	Seconds   *int64 `json:"gap_seconds"`
}
type TransferCap struct {
	MaxTransfers int `json:"max_transfers"`
	Raw          Gap `json:"raw"`
	Candidates   Gap `json:"candidates"`
	Displayed    Gap `json:"displayed"`
}
type Quality struct {
	TransferCaps    []TransferCap `json:"transfer_caps"`
	RawRegret       Gap           `json:"raw_ranking_regret"`
	CandidateRegret Gap           `json:"candidate_ranking_regret"`
	DisplayRegret   Gap           `json:"display_ranking_regret"`
	RawCount        int           `json:"raw_count"`
	CandidateCount  int           `json:"candidate_count"`
	DisplayedCount  int           `json:"displayed_count"`
}

func best(js []model.Validated, score func(model.Metrics) (int64, bool)) *int64 {
	var result *int64
	for _, j := range js {
		n, ok := score(j.Metrics)
		if ok && (result == nil || n < *result) {
			v := n
			result = &v
		}
	}
	return result
}
func gap(reference, observed *int64) (Gap, error) {
	g := Gap{Reference: reference, Observed: observed, Missing: reference != nil && observed == nil}
	if reference == nil && observed != nil {
		return g, fmt.Errorf("candidate reaches a reference-unreachable objective")
	}
	if reference != nil && observed != nil {
		n := *observed - *reference
		g.Seconds = &n
		if n < 0 {
			return g, fmt.Errorf("candidate improves declared exact reference by %d seconds", -n)
		}
	}
	return g, nil
}

// Compare requires an independently established complete arrival/boarding Pareto
// reference. The caller must withhold this comparison on reference failure.
func Compare(q model.Query, reference, raw, candidates, displayed []model.Validated, penalty int64) (Quality, error) {
	v := Quality{RawCount: len(raw), CandidateCount: len(candidates), DisplayedCount: len(displayed), TransferCaps: []TransferCap{}}
	if penalty < 0 {
		return v, fmt.Errorf("negative penalty")
	}
	for b := 1; b <= q.MaxBoardings; b++ {
		score := func(m model.Metrics) (int64, bool) { return m.Arrival, m.Boardings <= b }
		ref := best(reference, score)
		r, e := gap(ref, best(raw, score))
		if e != nil {
			return v, e
		}
		c, e := gap(ref, best(candidates, score))
		if e != nil {
			return v, e
		}
		d, e := gap(ref, best(displayed, score))
		if e != nil {
			return v, e
		}
		v.TransferCaps = append(v.TransferCaps, TransferCap{b - 1, r, c, d})
	}
	score := func(m model.Metrics) (int64, bool) { return m.Arrival - q.Departure + int64(m.Transfers)*penalty, true }
	ref := best(reference, score)
	var e error
	v.RawRegret, e = gap(ref, best(raw, score))
	if e != nil {
		return v, e
	}
	v.CandidateRegret, e = gap(ref, best(candidates, score))
	if e != nil {
		return v, e
	}
	v.DisplayRegret, e = gap(ref, best(displayed, score))
	return v, e
}

type Distribution struct {
	Count  int     `json:"count"`
	P50    float64 `json:"p50"`
	P95    float64 `json:"p95"`
	Max    float64 `json:"max"`
	Method string  `json:"method"`
}

// Summarize uses nearest-rank empirical quantiles. It does not imply a confidence
// interval or a population percentile from a small diagnostic sample.
func Summarize(values []float64) Distribution {
	d := Distribution{Count: len(values), Method: "nearest-rank empirical; no population percentile claim"}
	if len(values) == 0 {
		return d
	}
	v := append([]float64{}, values...)
	sort.Float64s(v)
	d.P50 = v[(len(v)+1)/2-1]
	d.P95 = v[(95*len(v)+99)/100-1]
	d.Max = v[len(v)-1]
	return d
}
