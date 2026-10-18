package evaluation_test

import (
	"github.com/ertyoii/transit-routing-bench/evaluation"
	"github.com/ertyoii/transit-routing-go/model"
	"testing"
)

func point(arrival int64, boardings int) model.Validated {
	return model.Validated{Metrics: model.Metrics{Arrival: arrival, Boardings: boardings, Transfers: max(0, boardings-1)}}
}
func TestRawVersusDisplayLossAndRankingOnlyRegret(t *testing.T) {
	q := model.Query{Departure: 100, MaxBoardings: 2}
	reference := []model.Validated{point(1000, 1), point(800, 2)}
	raw := []model.Validated{point(1100, 1), point(800, 2)}
	shown := raw[1:]
	r, e := evaluation.Compare(q, reference, raw, raw, shown, 300)
	if e != nil {
		t.Fatal(e)
	}
	if *r.TransferCaps[0].Raw.Seconds != 100 || !r.TransferCaps[0].Displayed.Missing || *r.RawRegret.Seconds != 100 || *r.DisplayRegret.Seconds != 100 {
		t.Fatalf("wrong quality %+v", r)
	}
	if raw[1].Metrics.Arrival != 800 {
		t.Fatal("ranking changed actual time")
	}
	r, e = evaluation.Compare(q, reference, nil, nil, nil, 300)
	if e != nil || !r.RawRegret.Missing || r.RawRegret.Seconds != nil {
		t.Fatal("missing candidate concealed by gap average")
	}
	if _, e = evaluation.Compare(q, reference, []model.Validated{point(700, 1)}, nil, nil, 300); e == nil {
		t.Fatal("reference counterexample ignored")
	}
}
func TestDiagnosticQuantiles(t *testing.T) {
	r := evaluation.Summarize([]float64{4, 1, 3, 2})
	if r.Count != 4 || r.P50 != 2 || r.P95 != 4 {
		t.Fatal(r)
	}
	if evaluation.Summarize(nil).Count != 0 {
		t.Fatal("empty samples")
	}
}
