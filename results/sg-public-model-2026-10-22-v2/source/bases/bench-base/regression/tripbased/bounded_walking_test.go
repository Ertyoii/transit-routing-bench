package tripbased_test

import (
	"context"
	"encoding/json"
	"math/rand/v2"
	"reflect"
	"slices"
	"testing"

	"github.com/ertyoii/transit-routing-bench/oracle"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/tripbased"
)

func boundedCompare(t *testing.T, d model.Dataset, q model.Query) *tripbased.BoundedWalkingTBIndex {
	t.Helper()
	o, e := oracle.Enumerate(context.Background(), d, q, oracle.Limits{MaxStates: 100000, MaxJourneys: 10000})
	if e != nil || !o.Complete {
		t.Fatalf("independent oracle incomplete: %v", e)
	}
	want := objectives(reconstructed(t, d, q, o.Journeys), q.MaxBoardings)
	x, e := tripbased.BuildBoundedWalkingTB(context.Background(), d, q.Destination, q.Walking.Transfer, trexConfig(0))
	if e != nil || !x.Complete() {
		t.Fatal(e)
	}
	r, e := x.Search(context.Background(), q)
	if e != nil || !r.Complete {
		t.Fatal(e)
	}
	got := objectives(reconstructed(t, d, q, r.Journeys), q.MaxBoardings)
	raw, _ := json.Marshal(map[string]any{"dataset": d, "query": q, "oracle": o, "result": r})
	t.Logf("CASE_JSON %s", raw)
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("want %v got %v d=%+v q=%+v", want, got, d, q)
	}
	return x
}

func TestBoundedWalkingTerminal1114AndCaps(t *testing.T) {
	d := data()
	trip(&d, "in", []string{"A", "B"}, 0, 1)
	trip(&d, "out", []string{"C", "D"}, 901, 902)
	trip(&d, "elsewhere", []string{"Y", "X"}, 0, 1)
	// A long transit-to-transit walk elsewhere must not forbid this query.
	d.Footpaths = []model.Footpath{{ID: "bc", From: "B", To: "C", Duration: 900, Accessible: model.Yes}, {ID: "xy", From: "X", To: "Y", Duration: 1114, Accessible: model.Yes}}
	q := query()
	q.LatestArrival = 2000
	q.MaxWalkSeconds = 6000
	q.Walking = &model.WalkingLimits{Access: 600, Egress: 600, Transfer: 900, Direct: 900}
	x := boundedCompare(t, d, q)
	r, _ := x.Search(context.Background(), q)
	if got := objectives(reconstructed(t, d, q, r.Journeys), q.MaxBoardings); got[2] != 902 {
		t.Fatal(got)
	}
	legacy, e := tripbased.BuildTREX(context.Background(), d, trexConfig(0))
	if e != nil {
		t.Fatal(e)
	}
	if r, e := legacy.Search(context.Background(), q); e == nil || r.Complete {
		t.Fatal("original ranked capability guard bypassed")
	}
	for _, role := range []string{"transfer", "access", "egress", "direct"} {
		qq := q
		w := *q.Walking
		qq.Walking = &w
		switch role {
		case "transfer":
			w.Transfer = 899
		case "access":
			qq.Origin = "B"
		case "egress":
			qq.Destination = "C"
		case "direct":
			qq.Origin = "X"
			qq.Destination = "Y"
		}
		boundedCompare(t, d, qq)
	}
}

func TestBoundedWalkingAbsorbingTargetDetour(t *testing.T) {
	d := data()
	trip(&d, "in", []string{"A", "B"}, 0, 1)
	trip(&d, "out", []string{"C", "D"}, 6, 7)
	trip(&d, "must-not-board-at-target", []string{"D", "C"}, 3, 4)
	// B-D-C is shortest, but B-D exceeds egress. Dropping the B-C
	// transfer loses the valid B-X-C detour. Allowing B-D-C is invalid.
	d.Footpaths = []model.Footpath{{ID: "bd", From: "B", To: "D", Duration: 2, Accessible: model.Yes}, {ID: "dc", From: "D", To: "C", Duration: 1, Accessible: model.Yes}, {ID: "bx", From: "B", To: "X", Duration: 2, Accessible: model.Yes}, {ID: "xc", From: "X", To: "C", Duration: 3, Accessible: model.Yes}}
	q := query()
	q.Walking = &model.WalkingLimits{Transfer: 5, Egress: 1}
	q.MaxWalkSeconds = 100
	x := boundedCompare(t, d, q)
	r, _ := x.Search(context.Background(), q)
	if got := objectives(reconstructed(t, d, q, r.Journeys), q.MaxBoardings); got[2] != 7 {
		t.Fatal(got)
	}
	if x.Snapshot().RemovedOutgoingWalks != 1 {
		t.Fatal("absorption unexercised")
	}
	// Removing the detour makes the two-ride journey infeasible.
	d.Footpaths = d.Footpaths[:2]
	boundedCompare(t, d, q)
}

func TestBoundedWalkingIndependentDirectedCorpus(t *testing.T) {
	for seed := uint64(0); seed < 120; seed++ {
		d, q := generated(seed)
		d.Transfers = nil
		q.TransferBuffer = 0
		q.AccessibleOnly = false
		for i := range d.Connections {
			d.Connections[i].Pickup = true
			d.Connections[i].Dropoff = true
		}
		rng := rand.New(rand.NewPCG(seed, 7981))
		q.Walking = &model.WalkingLimits{Access: int64(rng.IntN(8)), Egress: int64(rng.IntN(8)), Transfer: int64(rng.IntN(8)), Direct: int64(rng.IntN(8))}
		q.MaxWalkSeconds = 100
		q.MaxLegs = 64
		// Directed acyclic walks include transit-through-target counterexamples
		// and alternate paths. All raw feasible paths are enumerated by oracle.
		stops := []string{"A", "B", "C", "D"}
		d.Footpaths = nil
		for i := 0; i < 3; i++ {
			for j := i + 1; j < 4; j++ {
				if rng.IntN(2) == 0 {
					d.Footpaths = append(d.Footpaths, model.Footpath{ID: stops[i] + stops[j], From: stops[i], To: stops[j], Duration: int64(1 + rng.IntN(6)), Accessible: model.Yes})
				}
			}
		}
		boundedCompare(t, d, q)
	}
}

func TestBoundedWalkingResourcesAndOwnership(t *testing.T) {
	d, q, _ := trexFixture()
	x := boundedCompare(t, d, q)
	before := x.Snapshot()
	for _, kind := range []string{"destination", "walk-total", "legs", "buffer", "boards", "transfer-cap"} {
		qq := q
		switch kind {
		case "destination":
			qq.Destination = "Y"
		case "walk-total":
			qq.MaxWalkSeconds = 0
		case "legs":
			qq.MaxLegs = 1
		case "buffer":
			qq.TransferBuffer = 1
		case "boards":
			qq.MaxBoardings = 5
		case "transfer-cap":
			w := *q.Walking
			w.Transfer++
			qq.Walking = &w
		}
		if r, e := x.Search(context.Background(), qq); e == nil || r.Complete {
			t.Fatal(kind, "accepted")
		}
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if r, e := x.Search(ctx, q); e == nil || r.Complete {
		t.Fatal("cancel accepted")
	}
	c := trexConfig(0)
	c.Limits.MaxTransfers = 1
	partial, e := tripbased.BuildBoundedWalkingTB(context.Background(), d, q.Destination, q.Walking.Transfer, c)
	if e == nil || partial.Complete() {
		t.Fatal("partial build accepted")
	}
	if r, e := partial.Search(context.Background(), q); e == nil || r.Complete {
		t.Fatal("partial queried")
	}
	if _, e := tripbased.BuildBoundedWalkingTB(context.Background(), d, q.Destination, q.Walking.Transfer, trexConfig(1)); e == nil {
		t.Fatal("ranked cap composition accepted")
	}
	d.Connections[0].Arrival = 99
	copySnap := x.Snapshot()
	copySnap.Index.Lines[0][0] = "mutated"
	if !reflect.DeepEqual(before, x.Snapshot()) {
		t.Fatal("mutable snapshot/input alias")
	}
}

func TestBoundedWalkingTwoObjectivesAndReuse(t *testing.T) {
	d := data()
	trip(&d, "walk-fast", []string{"X", "D"}, 5, 10)
	trip(&d, "no-walk", []string{"A", "D"}, 0, 20)
	d.Footpaths = []model.Footpath{{ID: "ax", From: "A", To: "X", Duration: 5, Accessible: model.Yes}}
	q := query()
	q.MaxBoardings = 1
	q.Walking = &model.WalkingLimits{Access: 5}
	x := boundedCompare(t, d, q)
	r, e := x.Search(context.Background(), q)
	if e != nil || len(r.Journeys) != 1 {
		t.Fatal(r, e)
	}
	m := reconstructed(t, d, q, r.Journeys)[0]
	if m.Arrival != 10 || m.WalkingSeconds != 5 {
		t.Fatal(m)
	}
	// Oracle also contains the slower no-walk 3D-Pareto point. This API's
	// one-board label intentionally does not promise that third objective.
	o, e := oracle.Enumerate(context.Background(), d, q, oracle.Limits{MaxStates: 1000, MaxJourneys: 100})
	if e != nil {
		t.Fatal(e)
	}
	hasNoWalk := false
	for _, m := range reconstructed(t, d, q, o.Journeys) {
		if m.Arrival == 20 && m.WalkingSeconds == 0 {
			hasNoWalk = true
		}
	}
	if !hasNoWalk {
		t.Fatal("3D distinction unexercised")
	}
	before := x.Snapshot()
	for _, cap := range []int64{0, 5, 3, 5, 0} {
		qq := q
		w := *q.Walking
		w.Access = cap
		qq.Walking = &w
		r, e := x.Search(context.Background(), qq)
		if e != nil || !r.Complete {
			t.Fatal(e)
		}
		want := int64(20)
		if cap == 5 {
			want = 10
		}
		if got := objectives(reconstructed(t, d, qq, r.Journeys), 1); got[1] != want {
			t.Fatal(got, want)
		}
	}
	if !reflect.DeepEqual(before, x.Snapshot()) {
		t.Fatal("query mutated preparation")
	}
	slices.Reverse(d.Connections)
	slices.Reverse(d.Trips)
	slices.Reverse(d.Stops)
	boundedCompare(t, d, q)
	c := trexConfig(0)
	c.Limits.MaxQueryWork = 1
	limited, e := tripbased.BuildBoundedWalkingTB(context.Background(), d, q.Destination, q.Walking.Transfer, c)
	if e != nil {
		t.Fatal(e)
	}
	if r, e := limited.Search(context.Background(), q); e == nil || r.Complete {
		t.Fatal("query work exhaustion accepted")
	}
}

func FuzzBoundedWalkingOracle(f *testing.F) {
	for _, seed := range []uint64{0, 17, 63, 119} {
		f.Add(seed)
	}
	f.Fuzz(func(t *testing.T, seed uint64) {
		d, q := generated(seed)
		d.Transfers = nil
		q.TransferBuffer = 0
		q.AccessibleOnly = false
		for i := range d.Connections {
			d.Connections[i].Pickup = true
			d.Connections[i].Dropoff = true
		}
		q.Walking.Egress = int64(seed % 4)
		boundedCompare(t, d, q)
	})
}
