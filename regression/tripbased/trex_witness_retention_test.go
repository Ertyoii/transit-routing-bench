package tripbased_test

import (
	"context"
	"fmt"
	"github.com/ertyoii/transit-routing-go/tripbased"
	"math/rand/v2"
	"testing"
)

// The retained certificate set must cover every positive rank without storing
// another full witness that adds no rank support. This is an observable storage
// and budget contract; all query objectives are separately checked by raw words.
func TestTREXIrredundantRankWitnesses(t *testing.T) {
	for seed := uint64(98001); seed < 98101; seed++ {
		d := data()
		rng := rand.New(rand.NewPCG(seed, seed+5))
		stops := []string{"A", "B", "C", "D", "X", "Y"}
		for i := 0; i < 8; i++ {
			a := rng.IntN(6)
			b := (a + 1 + rng.IntN(5)) % 6
			c := (b + 1 + rng.IntN(5)) % 6
			dep := int64(rng.IntN(20))
			arr := dep + 1 + int64(rng.IntN(3))
			next := arr + int64(rng.IntN(3))
			trip(&d, fmt.Sprint(i), []string{stops[a], stops[b], stops[c]}, dep, arr, next, next+1+int64(rng.IntN(3)))
		}
		cfg := trexConfig(2)
		x, e := tripbased.BuildTREX(context.Background(), d, cfg)
		if e != nil {
			t.Fatal(e)
		}
		s := x.Snapshot()
		support := make([]int, len(s.Transfers))
		for _, w := range s.Witnesses {
			adds := false
			for _, id := range w.Transfers {
				if support[id] < w.Level+1 {
					adds = true
				}
			}
			if !adds {
				t.Fatalf("seed%d redundant full witness retained: %+v", seed, w)
			}
			for _, id := range w.Transfers {
				support[id] = max(support[id], w.Level+1)
			}
		}
		for id, e := range s.Transfers {
			if e.Rank != support[id] {
				t.Fatalf("unsupported rank seed%d edge%d", seed, id)
			}
		}
		cfg.Limits.MaxWitnesses = max(1, s.Stats.RankPromotions)
		y, e := tripbased.BuildTREX(context.Background(), d, cfg)
		if e != nil || !y.Complete() {
			t.Fatal("promotion-sized witness budget failed", seed, e)
		}
	}
}
