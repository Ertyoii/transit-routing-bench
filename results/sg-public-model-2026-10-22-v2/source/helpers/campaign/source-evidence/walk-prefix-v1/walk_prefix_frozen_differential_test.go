package tripbased

// This identical test is overlaid into the untouched frozen base and candidate.
// It invokes only closeWalksWithin, not CSA, a donor router or an oracle package.
import (
	"context"
	"encoding/json"
	"fmt"
	"math/rand"
	"os"
	"reflect"
	"testing"
	"time"

	"github.com/ertyoii/transit-routing-go/model"
)

type walkPrefixPollContext struct{ at, polls int }

func (*walkPrefixPollContext) Deadline() (time.Time, bool) { return time.Time{}, false }
func (*walkPrefixPollContext) Done() <-chan struct{}       { return nil }
func (*walkPrefixPollContext) Value(any) any               { return nil }
func (c *walkPrefixPollContext) Err() error {
	c.polls++
	if c.at > 0 && c.polls >= c.at {
		return context.Canceled
	}
	return nil
}

type walkPrefixCase struct {
	name  string
	names []string
	d     model.Dataset
}

func walkPrefixCases() []walkPrefixCase {
	names := []string{"A", "B", "C", "D", "X"}
	literal := walkPrefixCase{"ties-parallel-self-cycle-unreachable", names, model.Dataset{Footpaths: []model.Footpath{
		{ID: "ab2", From: "A", To: "B", Duration: 1, Provenance: "raw:ab2", Accessible: model.Yes},
		{ID: "cd", From: "C", To: "D", Duration: 1, Provenance: "raw:cd", Accessible: model.Yes},
		{ID: "ab1", From: "A", To: "B", Duration: 1, Provenance: "raw:ab1", Accessible: model.Yes},
		{ID: "ac", From: "A", To: "C", Duration: 1, Provenance: "raw:ac", Accessible: model.Yes},
		{ID: "bd", From: "B", To: "D", Duration: 1, Provenance: "raw:bd", Accessible: model.Yes},
		{ID: "aa", From: "A", To: "A", Duration: 1, Provenance: "raw:aa", Accessible: model.Yes},
		{ID: "da", From: "D", To: "A", Duration: 4, Provenance: "raw:da", Accessible: model.Yes},
	}}}
	out := []walkPrefixCase{literal, {"no-raw-edges", names, model.Dataset{}}}
	chain := walkPrefixCase{name: "reverse-lexical-chain", names: []string{}}
	for i := 0; i < 12; i++ {
		chain.names = append(chain.names, fmt.Sprintf("s%02d", i))
	}
	for i := 11; i > 0; i-- {
		chain.d.Footpaths = append(chain.d.Footpaths, model.Footpath{ID: fmt.Sprintf("e%02d", i), From: chain.names[i], To: chain.names[i-1], Duration: 1, Accessible: model.Yes})
	}
	out = append(out, chain)
	out = append(out, walkPrefixCase{"radius599-600-601-and-stale", names, model.Dataset{Footpaths: []model.Footpath{
		{ID: "ab", From: "A", To: "B", Duration: 599}, {ID: "bc", From: "B", To: "C", Duration: 1},
		{ID: "cd", From: "C", To: "D", Duration: 1}, {ID: "ac-old", From: "A", To: "C", Duration: 900},
	}}})
	out = append(out, walkPrefixCase{"service-domain-exceeded", names, model.Dataset{Footpaths: []model.Footpath{
		{ID: "ab", From: "A", To: "B", Duration: model.MaxServiceSecond}, {ID: "bc", From: "B", To: "C", Duration: 1},
	}}})
	for seed := int64(0); seed < 32; seed++ {
		rng := rand.New(rand.NewSource(seed))
		c := walkPrefixCase{name: fmt.Sprintf("independent-random-%02d", seed)}
		for i := 0; i < 7; i++ {
			c.names = append(c.names, fmt.Sprintf("s%d", i))
		}
		for i := 0; i < 20; i++ {
			c.d.Footpaths = append(c.d.Footpaths, model.Footpath{ID: fmt.Sprintf("e%02d", i), From: c.names[rng.Intn(7)], To: c.names[rng.Intn(7)], Duration: int64(1 + rng.Intn(6)), Accessible: model.Yes, Provenance: fmt.Sprintf("seed%d-edge%d", seed, i)})
		}
		out = append(out, c)
	}
	return out
}
func walkPrefixCarrier(c walkPrefixCase, work, settled, paths int) *FlashIndex {
	x := &FlashIndex{names: append([]string{}, c.names...), ids: map[string]int{}, cfg: FlashConfig{Limits: FlashLimits{MaxWork: work, MaxWalkSettled: settled, MaxClosurePaths: paths}}}
	for i, name := range x.names {
		x.ids[name] = i
	}
	return x
}

// Raw exhaustive SIMPLE path enumeration is independent of production Dijkstra.
// Strict positive edges make at least one minimum-distance path simple.
func walkPrefixRawDistances(c walkPrefixCase, source string, limit *int64) map[string]int64 {
	out := map[string]int64{source: 0}
	seen := map[string]bool{source: true}
	var visit func(string, int64)
	visit = func(at string, cost int64) {
		for _, e := range c.d.Footpaths {
			if e.From != at || seen[e.To] {
				continue
			}
			next := cost + e.Duration
			if limit != nil && next > *limit {
				continue
			}
			if old, ok := out[e.To]; !ok || next < old {
				out[e.To] = next
			}
			seen[e.To] = true
			visit(e.To, next)
			delete(seen, e.To)
		}
	}
	visit(source, 0)
	return out
}
func walkPrefixCheckWords(t *testing.T, c walkPrefixCase, x *FlashIndex, limit *int64, complete bool) {
	t.Helper()
	raw := map[string]model.Footpath{}
	for _, e := range c.d.Footpaths {
		raw[e.ID] = e
	}
	for source, row := range x.walks {
		got := map[string]int64{}
		for i, p := range row {
			at, cost := x.names[source], int64(0)
			for _, e := range p.Edges {
				if e.From != at || raw[e.ID] != e {
					t.Fatal("raw directed provenance changed", c.name, p, e)
				}
				at, cost = e.To, cost+e.Duration
			}
			if at != p.To || cost != p.Duration || limit != nil && cost > *limit {
				t.Fatal("word/length/radius changed", c.name, p)
			}
			got[p.To] = cost
			if x.walkMap[source] != nil && x.walkMap[source][x.ids[p.To]] != &x.walks[source][i] {
				t.Fatal("Path pointer identity changed")
			}
		}
		if complete && !reflect.DeepEqual(got, walkPrefixRawDistances(c, x.names[source], limit)) {
			t.Fatal("raw simple-path distance disagreement", c.name, source, got)
		}
	}
}
func TestWalkingPrefixFrozenDifferential(t *testing.T) {
	path := os.Getenv("WALK_PREFIX_RECORD")
	if path == "" {
		t.Fatal("WALK_PREFIX_RECORD is required; preserve each separate source output")
	}
	f, e := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if e != nil {
		t.Fatal(e)
	}
	defer f.Close()
	enc := json.NewEncoder(f)
	records := 0
	run := func(c walkPrefixCase, limit *int64, work, settled, paths, cancelAt int) *FlashIndex {
		x := walkPrefixCarrier(c, work, settled, paths)
		ctx := &walkPrefixPollContext{at: cancelAt}
		err := x.closeWalksWithin(c.d, &flashWork{ctx, x}, limit)
		msg := ""
		if err != nil {
			msg = err.Error()
		}
		walkPrefixCheckWords(t, c, x, limit, err == nil)
		if e := enc.Encode(map[string]any{"case": c.name, "limit": limit, "work_limit": work, "settled_limit": settled, "path_limit": paths, "cancel_at": cancelAt, "polls": ctx.polls, "error": msg, "stats": x.snap.Stats, "diameter": x.snap.ClosureDiameter, "walks": x.walks, "maps": x.walkMap}); e != nil {
			t.Fatal(e)
		}
		records++
		return x
	}
	for _, c := range walkPrefixCases() {
		for _, radius := range []int64{-1, 0, 1, 2, 5, 599, 600, 601} {
			var limit *int64
			if radius >= 0 {
				r := radius
				limit = &r
			}
			x := run(c, limit, 100000, 10000, 10000, 0)
			if c.name == "ties-parallel-self-cycle-unreachable" && limit == nil {
				p := x.walkMap[0][3]
				ids := []string{}
				for _, e := range p.Edges {
					ids = append(ids, e.ID)
				}
				if !reflect.DeepEqual(ids, []string{"ab1", "bd"}) {
					t.Fatal("native exact strict-tie word changed", ids)
				}
			}
		}
	}
	// Exhaust every exact work/cancellation/settlement/path boundary of one
	// cyclic tie fixture, retaining partial rows, maps and pre-hop path charges.
	c := walkPrefixCases()[0]
	for _, radius := range []int64{-1, 0, 2, 600} {
		var limit *int64
		if radius >= 0 {
			r := radius
			limit = &r
		}
		full := run(c, limit, 100000, 10000, 10000, 0)
		for n := 0; n <= full.snap.Stats.Work+1; n++ {
			run(c, limit, n, 10000, 10000, 0)
		}
		for n := 1; n <= full.snap.Stats.Work+1; n++ {
			run(c, limit, 100000, 10000, 10000, n)
		}
		for n := 0; n <= full.snap.Stats.WalkSettled+1; n++ {
			run(c, limit, 100000, n, 10000, 0)
		}
		for n := 0; n <= full.snap.Stats.ClosurePaths+1; n++ {
			run(c, limit, 100000, 10000, n, 0)
		}
	}
	// Also cover interruptions in the middle of a longer leaf word.
	chain := walkPrefixCases()[2]
	full := run(chain, nil, 100000, 10000, 10000, 0)
	for n := 1; n <= full.snap.Stats.Work+1; n++ {
		run(chain, nil, 100000, 10000, 10000, n)
	}
	if e := f.Sync(); e != nil {
		t.Fatal(e)
	}
	t.Logf("canonical closure records=%d; exact raw words/status/counters/poll count/partial rows/maps retained", records)
}
