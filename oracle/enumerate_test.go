package oracle_test

import (
	"context"
	"errors"
	"github.com/ertyoii/transit-routing-bench/fixtures"
	"github.com/ertyoii/transit-routing-bench/oracle"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/selection"
	"github.com/ertyoii/transit-routing-go/validate"
	"reflect"
	"slices"
	"sync"
	"testing"
)

var budget = oracle.Limits{MaxStates: 100000, MaxJourneys: 10000}

func fixture(t testing.TB) fixtures.Bundle {
	t.Helper()
	b, _, e := fixtures.Load("../testdata/tiny.manifest.json")
	if e != nil {
		t.Fatal(e)
	}
	return b
}
func solve(t testing.TB, d model.Dataset, q model.Query) []model.Validated {
	t.Helper()
	r, e := oracle.Enumerate(context.Background(), d, q, budget)
	if e != nil || !r.Complete {
		t.Fatalf("incomplete oracle: %v", e)
	}
	c, e := validate.New(d)
	if e != nil {
		t.Fatal(e)
	}
	vs := []model.Validated{}
	for _, j := range r.Journeys {
		v, e := c.Check(q, j)
		if e != nil {
			t.Fatalf("oracle witness rejected: %+v: %v", j, e)
		}
		vs = append(vs, v)
	}
	slices.SortFunc(vs, selection.Compare)
	return vs
}
func refs(j model.Validated) []string {
	r := []string{}
	for _, l := range j.Journey.Legs {
		r = append(r, l.Ref)
	}
	return r
}
func TestHandEnumeratedFixture(t *testing.T) {
	b := fixture(t)
	all := solve(t, b.Dataset, b.Queries[0])
	wantRefs := [][]string{{"ab", "fast-0"}, {"tie-0"}, {"stay-0", "stay-1"}, {"slow-0"}}
	wantArrivals := []int64{125, 130, 130, 140}
	if len(all) != len(wantRefs) {
		t.Fatalf("got %d journeys, want four: %+v", len(all), all)
	}
	for i, j := range all {
		if !reflect.DeepEqual(refs(j), wantRefs[i]) || j.Metrics.Arrival != wantArrivals[i] || j.Metrics.Boardings != 1 || j.Metrics.Transfers != 0 {
			t.Fatalf("rank %d: %+v", i, j)
		}
	}
	if all[0].Metrics.WalkingSeconds != 5 {
		t.Fatal("access walking was lost")
	}
	accessible := solve(t, b.Dataset, b.Queries[1])
	if len(accessible) != 2 || !reflect.DeepEqual(refs(accessible[1]), []string{"stay-0", "stay-1"}) {
		t.Fatalf("accessible filtering must permit passing B onboard: %+v", accessible)
	}
	night := solve(t, b.Dataset, b.Queries[2])
	if len(night) != 1 || night[0].Metrics.Arrival != 90060 {
		t.Fatal("service time >24h changed")
	}
	if len(solve(t, b.Dataset, b.Queries[3])) != 0 {
		t.Fatal("reverse/unreachable route invented")
	}
	same := solve(t, b.Dataset, b.Queries[4])
	if len(same) != 1 || len(same[0].Journey.Legs) != 0 || same[0].Metrics.Arrival != 90 {
		t.Fatal("origin=destination must be the empty journey")
	}
}
func TestEnumerationBudgetIsInconclusive(t *testing.T) {
	b := fixture(t)
	for _, l := range []oracle.Limits{{MaxStates: 1, MaxJourneys: 100}, {MaxStates: 100000, MaxJourneys: 1}} {
		r, e := oracle.Enumerate(context.Background(), b.Dataset, b.Queries[0], l)
		var truncated *oracle.TruncatedError
		if !errors.As(e, &truncated) || r.Complete {
			t.Fatalf("budget silently accepted: %+v %v", r, e)
		}
		if _, e = selection.Select(nil, r.Complete, selection.Spec{Mode: selection.TopK, K: 1}); e == nil {
			t.Fatal("incomplete top-k accepted")
		}
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	r, e := oracle.Enumerate(ctx, b.Dataset, b.Queries[0], budget)
	if !errors.Is(e, context.Canceled) || r.Complete {
		t.Fatal("cancelled enumeration must be incomplete")
	}
}
func TestInputPermutationAndTimeTranslation(t *testing.T) {
	b := fixture(t)
	q := b.Queries[0]
	before := solve(t, b.Dataset, q)
	slices.Reverse(b.Dataset.Connections)
	slices.Reverse(b.Dataset.Footpaths)
	slices.Reverse(b.Dataset.Stops)
	slices.Reverse(b.Dataset.Trips)
	if got := solve(t, b.Dataset, q); !reflect.DeepEqual(before, got) {
		t.Fatal("input order changed journeys")
	}
	const shift = 86400
	for i := range b.Dataset.Connections {
		b.Dataset.Connections[i].Departure += shift
		b.Dataset.Connections[i].Arrival += shift
	}
	q.Departure += shift
	q.LatestArrival += shift
	after := solve(t, b.Dataset, q)
	if len(before) != len(after) {
		t.Fatal("translation changed cardinality")
	}
	for i := range before {
		if before[i].Identity != after[i].Identity || before[i].Metrics.Arrival+shift != after[i].Metrics.Arrival || before[i].Metrics.WalkingSeconds != after[i].Metrics.WalkingSeconds {
			t.Fatal("translation changed semantics")
		}
	}
}
func TestUnrelatedComponentAndResourceRelaxation(t *testing.T) {
	b := fixture(t)
	q := b.Queries[0]
	before := solve(t, b.Dataset, q)
	b.Dataset.Stops = append(b.Dataset.Stops, model.Stop{ID: "island", Accessible: model.Yes})
	b.Dataset.Footpaths = append(b.Dataset.Footpaths, model.Footpath{ID: "island-loop", From: "island", To: "island", Duration: 1, Accessible: model.Yes})
	if after := solve(t, b.Dataset, q); !reflect.DeepEqual(before, after) {
		t.Fatal("disconnected component changed results")
	}
	q.MaxWalkSeconds = 60
	after := solve(t, b.Dataset, q)
	if len(after) == 0 || after[0].Metrics.Arrival > before[0].Metrics.Arrival {
		t.Fatal("relaxation worsened earliest arrival")
	}
}
func TestZeroDurationCyclesAndRepeatedPhysicalStop(t *testing.T) {
	d := model.Dataset{SchemaVersion: model.SchemaVersion, ID: "zero", TimeZone: "Asia/Singapore", ServiceDate: "2026-10-17", Stops: []model.Stop{{ID: "A", Accessible: model.Yes}, {ID: "D", Accessible: model.Yes}}, Trips: []model.Trip{{ID: "loop", Accessible: model.Yes}}, Connections: []model.Connection{
		{ID: "loop0", TripID: "loop", Sequence: 0, From: "A", To: "A", Departure: 0, Arrival: 0, Pickup: true, Dropoff: true},
		{ID: "loop1", TripID: "loop", Sequence: 1, From: "A", To: "D", Departure: 0, Arrival: 0, Pickup: true, Dropoff: true},
	}}
	q := model.Query{ID: "zero", Origin: "A", Destination: "D", Departure: 0, LatestArrival: 0, MaxBoardings: 3, MaxLegs: 3}
	js := solve(t, d, q)
	want := map[string]bool{"[loop1]": false, "[loop0 loop1]": false, "[loop0 loop0 loop1]": false}
	for _, j := range js {
		switch len(j.Journey.Legs) {
		case 1:
			want["[loop1]"] = true
		case 2:
			want["[loop0 loop1]"] = true
		case 3:
			want["[loop0 loop0 loop1]"] = true
		}
	}
	if len(js) != 3 {
		t.Fatalf("expected three bounded legal journeys, got %d", len(js))
	}
	for k, found := range want {
		if !found {
			t.Fatalf("physical stop was pruned: %s", k)
		}
	}
}
func TestConcurrentReadAndQueryPartitionInvariance(t *testing.T) {
	b := fixture(t)
	expected := map[string][]model.Validated{}
	for _, q := range b.Queries {
		expected[q.ID] = solve(t, b.Dataset, q)
	}
	// This checks the reference boundary; it does not claim to test a future batched CSA.
	for _, chunk := range []int{1, 2, 5} {
		queries := slices.Clone(b.Queries)
		slices.Reverse(queries)
		for start := 0; start < len(queries); start += chunk {
			end := min(start+chunk, len(queries))
			var wg sync.WaitGroup
			for _, q := range queries[start:end] {
				wg.Go(func() {
					result, err := oracle.Enumerate(context.Background(), b.Dataset, q, budget)
					if err != nil {
						t.Errorf("query %s: %v", q.ID, err)
						return
					}
					checker, err := validate.New(b.Dataset)
					if err != nil {
						t.Errorf("checker: %v", err)
						return
					}
					got := []model.Validated{}
					for _, journey := range result.Journeys {
						validated, err := checker.Check(q, journey)
						if err != nil {
							t.Errorf("query %s: %v", q.ID, err)
							return
						}
						got = append(got, validated)
					}
					slices.SortFunc(got, selection.Compare)
					if !reflect.DeepEqual(got, expected[q.ID]) {
						t.Errorf("chunk %d query %s changed", chunk, q.ID)
					}
				})
			}
			wg.Wait()
		}
	}
}
func FuzzTinyOracle(f *testing.F) {
	f.Add([]byte{0, 1, 2, 3, 4, 5, 6, 7})
	f.Add([]byte{255, 0, 255, 0})
	f.Add([]byte{0})
	f.Fuzz(func(t *testing.T, data []byte) {
		if len(data) == 0 {
			return
		}
		if len(data) > 64 {
			data = data[:64]
		}
		pick := func(i int) int { return int(data[i%len(data)]) }
		d := model.Dataset{SchemaVersion: model.SchemaVersion, ID: "fuzz", TimeZone: "Asia/Singapore", ServiceDate: "2026-10-17", Stops: []model.Stop{{ID: "A", Accessible: model.Yes}, {ID: "B", Accessible: model.Yes}, {ID: "C", Accessible: model.Yes}}}
		ids := []string{"A", "B", "C"}
		for i := 0; i < 4; i++ {
			id := string(rune('a' + i))
			dep := int64(pick(i+2) % 10)
			d.Trips = append(d.Trips, model.Trip{ID: id, Accessible: model.Yes})
			d.Connections = append(d.Connections, model.Connection{ID: id, TripID: id, From: ids[pick(i)%3], To: ids[pick(i+1)%3], Departure: dep, Arrival: dep + int64(pick(i+3)%4), Pickup: pick(i+4)%2 == 0, Dropoff: pick(i+5)%2 == 0})
		}
		for i := 0; i < 2; i++ {
			d.Footpaths = append(d.Footpaths, model.Footpath{ID: string(rune('w' + i)), From: ids[pick(i+6)%3], To: ids[pick(i+7)%3], Duration: 1 + int64(pick(i+8)%3), Accessible: model.Yes})
		}
		q := model.Query{ID: "fuzz", Origin: "A", Destination: "C", Departure: 0, LatestArrival: 15, TransferBuffer: int64(pick(0) % 3), MaxWalkSeconds: 6, MaxBoardings: 3, MaxLegs: 3}
		before := solve(t, d, q)
		slices.Reverse(d.Connections)
		slices.Reverse(d.Footpaths)
		after := solve(t, d, q)
		if !reflect.DeepEqual(before, after) {
			t.Fatal("order-dependent tiny oracle")
		}
		if _, e := selection.Select(before, true, selection.Spec{Mode: selection.TopK, K: 5}); e != nil {
			t.Fatal(e)
		}
	})
}
