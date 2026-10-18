package paper_test

import (
	"context"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/paper"
	"strings"
	"testing"
)

func TestRelevantWalkingBoundTiesCancellationAndExhaustion(t *testing.T) {
	d, q := base()
	q.MaxBoardings = 1
	q.MaxLegs = 2
	q.MaxWalkSeconds = 100
	q.Walking = &model.WalkingLimits{Access: 10}
	add(&d, "exit", ride("B", "D", 3, 4))
	d.Footpaths = []model.Footpath{{ID: "direct", From: "A", To: "B", Duration: 2, Accessible: model.Yes}, {ID: "first", From: "A", To: "C", Duration: 1, Accessible: model.Yes}, {ID: "second", From: "C", To: "B", Duration: 1, Accessible: model.Yes}}
	p, e := paper.New(d)
	if e != nil {
		t.Fatal(e)
	}
	proof, e := p.CertifyLegBound(context.Background(), q, paper.DefaultProofLimits())
	if e != nil || proof.Method != "relevant_endpoint_shortest_walk_hops" || proof.SufficientLegs != 3 {
		t.Fatal(proof, e)
	}
	if e = p.Check(q); e == nil {
		t.Fatal("equal-duration maximum-hop witness was not bounded")
	}
	for _, limits := range []paper.ProofLimits{{MaxSettled: 1, MaxEdges: 100}, {MaxSettled: 100, MaxEdges: 1}} {
		_, e = p.CertifyLegBound(context.Background(), q, limits)
		if e == nil || !strings.Contains(e.Error(), "exhausted") {
			t.Fatal("incomplete proof accepted", e)
		}
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, e = p.CertifyLegBound(ctx, q, paper.DefaultProofLimits()); e == nil {
		t.Fatal("cancelled proof accepted")
	}
	// The shortest-time path has two edges, even though a slower one-edge path
	// fits the leg budget. Paper dominance cannot certify that binding budget.
	d.Footpaths[0].Duration = 3
	p, e = paper.New(d)
	if e != nil {
		t.Fatal(e)
	}
	if e = p.Check(q); e == nil {
		t.Fatal("binding resource was silently relaxed")
	}
}
