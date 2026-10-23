package csa_test

import (
	"context"
	"github.com/ertyoii/transit-routing-bench/fixtures"
	"github.com/ertyoii/transit-routing-bench/oracle"
	"github.com/ertyoii/transit-routing-go/csa"
	"github.com/ertyoii/transit-routing-go/model"
	"reflect"
	"slices"
	"testing"
)

func TestStratifiedCapsAgainstExhaustiveUniverseAndBatchPartitions(t *testing.T) {
	b, _, err := fixtures.Load("../../testdata/tiny.manifest.json")
	if err != nil {
		t.Fatal(err)
	}
	idx, err := csa.New(b.Dataset)
	if err != nil {
		t.Fatal(err)
	}
	cfg := csa.Config{MaxLabels: 300000, MaxJourneys: 100000, ExactTopK: 3}
	want := map[string][]model.Validated{}
	for _, q := range b.Queries {
		single, err := idx.StratifiedSingle(context.Background(), q, cfg)
		if err != nil || !single.CapComplete || single.Complete || single.TopKComplete || len(single.CapResults) != q.MaxBoardings+1 {
			t.Fatalf("bad parent contract: %+v %v", single, err)
		}
		union := map[string]model.Validated{}
		for cap, got := range single.CapResults {
			cq := q
			cq.MaxBoardings = cap
			o, err := oracle.Enumerate(context.Background(), b.Dataset, cq, oracle.Limits{MaxStates: 300000, MaxJourneys: 100000})
			if err != nil || !o.Complete {
				t.Fatalf("inconclusive oracle: %v", err)
			}
			ordered := canonical(t, b.Dataset, cq, o.Journeys)
			expected := ordered[:min(cfg.ExactTopK, len(ordered))]
			if got.MaxBoardings != cap || !got.Result.TopKComplete || !reflect.DeepEqual(canonical(t, b.Dataset, cq, got.Result.Journeys), expected) {
				t.Fatalf("cap %d differs from exhaustive top-k", cap)
			}
			for _, v := range expected {
				union[v.Identity] = v
			}
		}
		got := canonical(t, b.Dataset, q, single.Journeys)
		if len(got) != len(union) {
			t.Fatal("union lost or duplicated identities")
		}
		for _, v := range got {
			if !reflect.DeepEqual(v, union[v.Identity]) {
				t.Fatal("union differs")
			}
		}
		want[q.ID] = got
	}
	for _, reverse := range []bool{false, true} {
		qs := append([]model.Query{}, b.Queries...)
		if reverse {
			slices.Reverse(qs)
		}
		for _, size := range []int{1, 2, len(qs)} {
			for from := 0; from < len(qs); from += size {
				part := qs[from:min(from+size, len(qs))]
				batch, err := idx.StratifiedShared(context.Background(), part, cfg)
				if err != nil {
					t.Fatal(err)
				}
				for i, q := range part {
					if !batch.Results[i].CapComplete || !reflect.DeepEqual(canonical(t, b.Dataset, q, batch.Results[i].Journeys), want[q.ID]) {
						t.Fatal("batch partition/order changed results")
					}
				}
			}
		}
	}
	q := b.Queries[0]
	partial, err := idx.StratifiedSingle(context.Background(), q, csa.Config{MaxLabels: 1, MaxJourneys: 10, ExactTopK: 3})
	if err == nil || partial.CapComplete || partial.Complete || partial.TopKComplete {
		t.Fatal("budget failed union certified")
	}
	q.MaxBoardings = -1
	if _, err = idx.StratifiedSingle(context.Background(), q, cfg); err == nil {
		t.Fatal("invalid original query accepted")
	}
}
