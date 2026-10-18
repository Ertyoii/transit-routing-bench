package mcraptor_test

import (
	"context"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/raptor"
	"reflect"
	"sync"
	"testing"
)

// The whole-word assessor and generator predate this accelerator. Expected
// vectors come from complete finite words, never from the unpruned router.
func TestEarlyPruningIndependentWords(t *testing.T) {
	for seed := uint64(0); seed < 64; seed++ {
		d, q := generated(seed)
		all := fullWords(d, q, 7)
		want := pareto(all)
		x, e := raptor.New(d)
		if e != nil {
			t.Fatal(e)
		}
		for _, enabled := range []bool{false, true} {
			config := cfg()
			config.EarlyPruning = enabled
			r, e := x.SearchMulti(context.Background(), q, config)
			if e != nil || !r.Complete {
				t.Fatal(seed, e, r)
			}
			for _, penalty := range []int64{0, 3, 300} {
				best := func(ms []model.Metrics) int64 {
					score := inf
					for _, m := range ms {
						score = min(score, m.Arrival-q.Departure+penalty*int64(max(0, m.Boardings-1)))
					}
					return score
				}
				if got, expected := best(metrics(t, d, q, r.Journeys)), best(all); got != expected {
					t.Fatalf("seed %d penalty %d want %d got %d", seed, penalty, expected, got)
				}
			}
			if got := pareto(metrics(t, d, q, r.Journeys)); !reflect.DeepEqual(got, want) {
				t.Fatalf("seed %d enabled %v want %v got %v", seed, enabled, want, got)
			}
		}
		plain, e := x.Search(context.Background(), q)
		if e != nil {
			t.Fatal(e)
		}
		pruned, _, e := x.SearchEarlyPruning(context.Background(), q)
		if e != nil || !pruned.Complete {
			t.Fatal(e)
		}
		expected := []model.Metrics{}
		for _, v := range want {
			expected = append(expected, model.Metrics{Arrival: v.Arrival, Boardings: v.Boards})
		}
		for _, js := range [][]model.Journey{plain.Journeys, pruned.Journeys} {
			if got, w := objectives(metrics(t, d, q, js), q.MaxBoardings), objectives(expected, q.MaxBoardings); !reflect.DeepEqual(got, w) {
				t.Fatalf("seed %d 2D want %v got %v", seed, w, got)
			}
		}
	}
}

func checkEarly(t *testing.T, d model.Dataset, q model.Query, want []vector) (*raptor.Index, raptor.MultiResult) {
	t.Helper()
	x, e := raptor.New(d)
	if e != nil {
		t.Fatal(e)
	}
	config := cfg()
	config.EarlyPruning = true
	r, e := x.SearchMulti(context.Background(), q, config)
	if e != nil || !r.Complete {
		t.Fatal(e, r)
	}
	if got := pareto(metrics(t, d, q, r.Journeys)); !reflect.DeepEqual(got, want) {
		t.Fatalf("want %v got %v", want, got)
	}
	return x, r
}

func TestEarlyPruningSortedTailAndEquality(t *testing.T) {
	d, q := data(), query()
	trip(&d, "direct", []string{"A", "D"}, 1, 10)
	trip(&d, "feed", []string{"A", "X"}, 0, 2)
	trip(&d, "finish", []string{"C", "D"}, 3, 5)
	// Destination order puts the dominated long B path before useful short C.
	d.Footpaths = []model.Footpath{{ID: "long", From: "X", To: "B", Duration: 8, Accessible: model.Yes}, {ID: "short", From: "X", To: "C", Duration: 1, Accessible: model.Yes}}
	trip(&d, "unused", []string{"B", "Y"}, 20, 21)
	x, r := checkEarly(t, d, q, []vector{{10, 1, 0}, {5, 2, 1}})
	if r.Stats.EarlyPruning.Breaks == 0 || r.Stats.EarlyPruning.Skipped == 0 {
		t.Fatal("pruning never exercised", r.Stats)
	}
	p, s, e := x.SearchEarlyPruning(context.Background(), q)
	if e != nil || !p.Complete || s.Breaks == 0 {
		t.Fatal(e, s)
	}
	if got := objectives(metrics(t, d, q, p.Journeys), 3); !reflect.DeepEqual(got, []int64{inf, 10, 5, 5}) {
		t.Fatal(got)
	}
}

func TestEarlyPruningWalkingAndBoardingTradeoffs(t *testing.T) {
	d, q := data(), query()
	// Faster target walk cannot dominate the slower seated journey's walking cost.
	d.Footpaths = []model.Footpath{{ID: "direct-walk", From: "A", To: "D", Duration: 4, Accessible: model.Yes}, {ID: "access", From: "A", To: "B", Duration: 1, Accessible: model.Yes}}
	trip(&d, "seated", []string{"A", "C"}, 0, 5)
	trip(&d, "walk-feed", []string{"B", "C"}, 1, 3)
	trip(&d, "finish", []string{"C", "D"}, 6, 10)
	checkEarly(t, d, q, []vector{{4, 0, 4}, {10, 2, 0}})
	// A faster two-boarding answer from round two must not erase the
	// slower one-boarding egress already retained from round one. This
	// checks baseline completed-frontier maintenance, including pruning-off.
	d, q = data(), query()
	trip(&d, "feed", []string{"A", "B"}, 0, 1)
	trip(&d, "fast", []string{"B", "D"}, 1, 5)
	trip(&d, "slow", []string{"A", "X"}, 0, 6)
	d.Footpaths = []model.Footpath{{ID: "egress", From: "X", To: "D", Duration: 2, Accessible: model.Yes}}
	checkEarly(t, d, q, []vector{{8, 1, 2}, {5, 2, 0}})
}

func TestEarlyPruningRawDurationBeforeTransferRules(t *testing.T) {
	d, q := data(), query()
	trip(&d, "direct", []string{"A", "D"}, 0, 10)
	trip(&d, "feed", []string{"A", "X"}, 0, 2)
	trip(&d, "short-unused", []string{"B", "Y"}, 30, 31)
	trip(&d, "finish", []string{"C", "D"}, 4, 5)
	d.Footpaths = []model.Footpath{{ID: "short", From: "X", To: "B", Duration: 1, Accessible: model.Yes}, {ID: "long", From: "X", To: "C", Duration: 2, Accessible: model.Yes}}
	d.Transfers = []model.TransferRule{{ID: "wait", FromStop: "X", ToStop: "B", Type: 2, MinSeconds: 20}}
	checkEarly(t, d, q, []vector{{10, 1, 0}, {5, 2, 2}})
}

func TestEarlyPruningFailuresAndQueryIsolation(t *testing.T) {
	d, q := data(), query()
	trip(&d, "through", []string{"A", "B", "D"}, 1, 2, 2, 4)
	d.Connections[0].Dropoff = false
	d.Connections[1].Pickup = false
	d.Stops[1].Accessible = model.No
	q.AccessibleOnly = true
	q.TransferBuffer = 100
	x, _ := checkEarly(t, d, q, []vector{{4, 1, 0}})
	config := cfg()
	config.EarlyPruning = true
	for _, bad := range []raptor.MultiConfig{
		{EarlyPruning: true, Criterion: "fare", MaxLabels: 100, MaxConnectionVisits: 100},
		{EarlyPruning: true, Criterion: "walking_seconds", MaxLabels: 1, MaxConnectionVisits: 100},
		{EarlyPruning: true, Criterion: "walking_seconds", MaxLabels: 100, MaxConnectionVisits: 1},
	} {
		r, e := x.SearchMulti(context.Background(), q, bad)
		if e == nil || r.Complete {
			t.Fatal("budget/capability accepted", r)
		}
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	r, e := x.SearchMulti(ctx, q, config)
	if e == nil || r.Complete {
		t.Fatal("cancel accepted")
	}
	p, _, e := x.SearchEarlyPruning(ctx, q)
	if e == nil || p.Complete {
		t.Fatal("cancel accepted")
	}
	type answer struct {
		q   model.Query
		r   raptor.MultiResult
		err error
	}
	out := make(chan answer, 12)
	var wg sync.WaitGroup
	for i := 0; i < 12; i++ {
		query := q
		if i%2 == 1 {
			query.Destination = "C"
		}
		wg.Add(1)
		go func() {
			defer wg.Done()
			r, e := x.SearchMulti(context.Background(), query, config)
			out <- answer{query, r, e}
		}()
	}
	wg.Wait()
	close(out)
	for a := range out {
		if a.err != nil || !a.r.Complete {
			t.Fatal(a)
		}
		want := []vector{}
		if a.q.Destination == "D" {
			want = []vector{{4, 1, 0}}
		}
		if got := pareto(metrics(t, d, a.q, a.r.Journeys)); !reflect.DeepEqual(got, want) {
			t.Fatal(got, want)
		}
	}
}

func FuzzEarlyPruningIndependent(f *testing.F) {
	f.Add(uint64(0))
	f.Add(uint64(31))
	f.Fuzz(func(t *testing.T, seed uint64) {
		d, q := generated(seed)
		want := pareto(fullWords(d, q, 7))
		x, e := raptor.New(d)
		if e != nil {
			t.Fatal(e)
		}
		config := cfg()
		config.EarlyPruning = true
		r, e := x.SearchMulti(context.Background(), q, config)
		if e != nil || !r.Complete {
			t.Fatal(e, r)
		}
		if got := pareto(metrics(t, d, q, r.Journeys)); !reflect.DeepEqual(got, want) {
			t.Fatalf("seed %d want %v got %v", seed, want, got)
		}
	})
}
