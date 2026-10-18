package corech_test

import (
	"context"
	"fmt"
	"github.com/ertyoii/transit-routing-go/corech"
	"github.com/ertyoii/transit-routing-go/model"
	"math/rand/v2"
	"reflect"
	"slices"
	"sync"
	"testing"
)

const far int64 = 1 << 50

func cfg(n int) corech.Config {
	return corech.Config{TargetCoreVertices: 2, MaximumAverageCoreOutDegree: 1000, WitnessSettledPerSearch: 64, MaxContractions: n + 1, MaxArcs: 100000, MaxWitnessSettled: 100000, MaxWitnessEdges: 100000}
}
func qcfg() corech.QueryLimits {
	return corech.QueryLimits{MaxSettled: 100000, MaxEdges: 100000, MaxUnpackedEdges: 100000}
}
func edge(id, a, b string, w int64) model.Footpath {
	return model.Footpath{ID: id, From: a, To: b, Duration: w, Accessible: model.Unknown}
}

// Independent all-pairs dynamic programming. No production heap, contraction,
// witness, traversal, path-unpacking or pruning helper constructs expected values.
func floyd(vs []string, es []model.Footpath) map[string]map[string]int64 {
	d := map[string]map[string]int64{}
	for _, u := range vs {
		d[u] = map[string]int64{}
		for _, v := range vs {
			d[u][v] = far
		}
		d[u][u] = 0
	}
	for _, e := range es {
		d[e.From][e.To] = min(d[e.From][e.To], e.Duration)
	}
	for _, k := range vs {
		for _, i := range vs {
			for _, j := range vs {
				d[i][j] = min(d[i][j], d[i][k]+d[k][j])
			}
		}
	}
	return d
}
func inspect(t testing.TB, vs []string, es []model.Footpath, x *corech.Index, cap int64) {
	t.Helper()
	s := x.Snapshot()
	if !s.Complete {
		t.Fatal(s.Error)
	}
	d := floyd(vs, es)
	raw := map[string]model.Footpath{}
	for _, e := range es {
		raw[e.ID] = e
	}
	core := []string{}
	for _, n := range s.Nodes {
		if n.Protected && !n.Core {
			t.Fatal("protected vertex contracted")
		}
		if n.Core {
			core = append(core, n.ID)
		}
	}
	// Check every shortcut algebraically against its original-edge DAG. This is
	// independent of query unpacking and rejects a fabricated low-cost shortcut.
	for i, a := range s.Arcs {
		if a.Left < 0 {
			e, ok := raw[a.RawRef]
			if !ok || e.Duration != a.Duration || e.From != s.Nodes[a.From].ID || e.To != s.Nodes[a.To].ID {
				t.Fatal("invalid original arc", a)
			}
		} else {
			if a.Left >= i || a.Right < 0 || a.Right >= i {
				t.Fatal("bad DAG", a)
			}
			l, r := s.Arcs[a.Left], s.Arcs[a.Right]
			if l.From != a.From || l.To != r.From || r.To != a.To || l.Duration+r.Duration != a.Duration {
				t.Fatal("invalid shortcut", a)
			}
		}
	}
	for _, u := range core {
		r, e := x.SearchMany(context.Background(), u, core, cap, qcfg())
		if e != nil || !r.Complete || len(r.Paths) != len(core) {
			t.Fatal(r, e)
		}
		for _, p := range r.Paths {
			want := d[u][p.Target]
			found := want < far && want <= cap
			if p.Found != found || found && p.Duration != want {
				t.Fatalf("%s -> %s want %d got %+v; %+v %+v", u, p.Target, want, p, vs, es)
			}
			at := u
			sum := int64(0)
			for _, id := range p.RawEdges {
				w, ok := raw[id]
				if !ok || w.From != at {
					t.Fatal("bad independently checked raw witness", p)
				}
				at = w.To
				sum += w.Duration
			}
			if found && (at != p.Target || sum != want) {
				t.Fatal("raw witness cost/end mismatch", p)
			}
			if !found && (len(p.RawEdges) > 0 || len(p.CoreArcs) > 0) {
				t.Fatal("unreachable result has path", p)
			}
		}
	}
}
func generated(seed uint64) ([]string, []model.Footpath, []string, corech.Config) {
	r := rand.New(rand.NewPCG(seed, seed+83))
	n := 2 + r.IntN(7)
	vs := []string{}
	for i := 0; i < n; i++ {
		vs = append(vs, fmt.Sprintf("V%d", i))
	}
	es := []model.Footpath{}
	for i := 0; i < n; i++ {
		for j := 0; j < n; j++ {
			if r.IntN(4) == 0 {
				es = append(es, edge(fmt.Sprintf("e%d", len(es)), vs[i], vs[j], 1+int64(r.IntN(9))))
				if r.IntN(4) == 0 {
					es = append(es, edge(fmt.Sprintf("e%d", len(es)), vs[i], vs[j], 1+int64(r.IntN(9))))
				}
			}
		}
	}
	c := cfg(n)
	c.WitnessSettledPerSearch = []int{1, 3, 64}[r.IntN(3)]
	if r.IntN(4) == 0 {
		c.TargetCoreVertices = n / 2
	}
	return vs, es, []string{vs[0], vs[n-1]}, c
}
func TestAllPairsIndependentCorpus(t *testing.T) {
	for seed := uint64(0); seed < 768; seed++ {
		vs, es, ps, c := generated(seed)
		x, e := corech.Build(context.Background(), vs, es, ps, c)
		if e != nil {
			t.Fatal(seed, e)
		}
		inspect(t, vs, es, x, far)
		inspect(t, vs, es, x, 5)
	}
	t.Log("768 complete finite directed graphs; independent Floyd-Warshall distances for every retained-core ordered pair, at unrestricted and five-second limits")
}
func TestWitnessTiesAndConservativeLocalLimit(t *testing.T) {
	vs := []string{"A", "X", "Y", "B"}
	es := []model.Footpath{edge("ax", "A", "X", 3), edge("xb", "X", "B", 4), edge("ay", "A", "Y", 2), edge("yb", "Y", "B", 5)}
	c := cfg(4)
	c.TargetCoreVertices = 3
	x, e := corech.Build(context.Background(), vs, es, []string{"A", "B", "Y"}, c)
	if e != nil || x.Stats().Shortcuts != 0 || x.Stats().WitnessOmissions == 0 {
		t.Fatal(x.Stats(), e)
	}
	inspect(t, vs, es, x, far)
	c.WitnessSettledPerSearch = 1
	x, e = corech.Build(context.Background(), vs, es, []string{"A", "B", "Y"}, c)
	if e != nil || x.Stats().LimitedWitnessSearches == 0 || x.Stats().Shortcuts != 1 {
		t.Fatal(x.Stats(), e)
	}
	inspect(t, vs, es, x, far)
}
func TestNestedUnpackingPermutationPartitionAndIsolation(t *testing.T) {
	vs := []string{"A", "X", "Y", "B"}
	es := []model.Footpath{edge("ax", "A", "X", 1), edge("xy", "X", "Y", 1), edge("yb", "Y", "B", 1)}
	c := cfg(4)
	x, e := corech.Build(context.Background(), vs, es, []string{"A", "B"}, c)
	if e != nil {
		t.Fatal(e)
	}
	r, e := x.SearchMany(context.Background(), "A", []string{"B", "A"}, 3, qcfg())
	if e != nil || !reflect.DeepEqual(r.Paths[0].RawEdges, []string{"ax", "xy", "yb"}) {
		t.Fatal(r, e)
	}
	snap := x.Snapshot()
	nested := false
	for _, a := range snap.Arcs {
		if a.Left >= 0 && (snap.Arcs[a.Left].Left >= 0 || snap.Arcs[a.Right].Left >= 0) {
			nested = true
		}
	}
	if !nested {
		t.Fatal("fixture did not exercise recursive shortcut")
	}
	for _, ts := range [][]string{{"A", "B"}, {"B"}, {"A"}} {
		rr, e := x.SearchMany(context.Background(), "A", ts, 3, qcfg())
		if e != nil {
			t.Fatal(e)
		}
		for _, p := range rr.Paths {
			for _, o := range r.Paths {
				if p.Target == o.Target && !reflect.DeepEqual(p, o) {
					t.Fatal("partition/order changed path", p, o)
				}
			}
		}
	}
	slices.Reverse(vs)
	slices.Reverse(es)
	y, e := corech.Build(context.Background(), vs, es, []string{"B", "A"}, c)
	if e != nil || !reflect.DeepEqual(x.Snapshot(), y.Snapshot()) {
		t.Fatal("input permutation changed index", e)
	}
	vs[0] = "mutated"
	es[0].Duration = 99
	snap.Nodes[0].ID = "changed"
	snap.Arcs[0].Duration = 999
	rr, e := x.SearchMany(context.Background(), "A", []string{"B", "A"}, 3, qcfg())
	if e != nil || !reflect.DeepEqual(rr, r) {
		t.Fatal("index aliases caller snapshots", e)
	}
	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			rr, e := x.SearchMany(context.Background(), "A", []string{"B", "A"}, 3, qcfg())
			if e != nil || !reflect.DeepEqual(rr, r) {
				t.Error(rr, e)
			}
		}()
	}
	wg.Wait()
}
func TestGlobalFailureAndQueryLimitsNeverCertifyPartial(t *testing.T) {
	vs := []string{"A", "X", "Y", "B"}
	es := []model.Footpath{edge("ax", "A", "X", 1), edge("xy", "X", "Y", 1), edge("yb", "Y", "B", 1)}
	for _, which := range []string{"contractions", "arcs", "settled", "edges"} {
		c := cfg(4)
		switch which {
		case "contractions":
			c.MaxContractions = 1
		case "arcs":
			c.MaxArcs = 1
		case "settled":
			c.MaxWitnessSettled = 1
		case "edges":
			c.MaxWitnessEdges = 1
		}
		x, e := corech.Build(context.Background(), vs, es, []string{"A", "B"}, c)
		if e == nil || x.Complete() {
			t.Fatal("partial build accepted", which, e)
		}
		if r, e := x.SearchMany(context.Background(), "A", []string{"B"}, 4, qcfg()); e == nil || r.Complete {
			t.Fatal("query accepted incomplete index")
		}
	}
	x, e := corech.Build(context.Background(), vs, es, []string{"A", "B"}, cfg(4))
	if e != nil {
		t.Fatal(e)
	}
	for _, l := range []corech.QueryLimits{{MaxSettled: 1, MaxEdges: 100, MaxUnpackedEdges: 100}, {MaxSettled: 100, MaxEdges: 100, MaxUnpackedEdges: 2}} {
		r, e := x.SearchMany(context.Background(), "A", []string{"B"}, 4, l)
		if e == nil || r.Complete {
			t.Fatal("partial query accepted", r, e)
		}
	}
	// Identity graph has two outgoing edges, forcing the edge-visit budget.
	c := cfg(4)
	c.TargetCoreVertices = 4
	identity, e := corech.Build(context.Background(), vs, append(es, edge("ay", "A", "Y", 3)), []string{"A", "B"}, c)
	if e != nil {
		t.Fatal(e)
	}
	if r, e := identity.SearchMany(context.Background(), "A", []string{"B"}, 4, corech.QueryLimits{MaxSettled: 100, MaxEdges: 1, MaxUnpackedEdges: 100}); e == nil || r.Complete {
		t.Fatal(r, e)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if r, e := x.SearchMany(ctx, "A", []string{"B"}, 4, qcfg()); e == nil || r.Complete {
		t.Fatal(r, e)
	}
	if ix, e := corech.Build(ctx, vs, es, []string{"A", "B"}, cfg(4)); e == nil || ix.Complete() {
		t.Fatal(e)
	}
	if r, e := x.SearchMany(context.Background(), "X", []string{"B"}, 4, qcfg()); e == nil || r.Complete {
		t.Fatal("contracted endpoint accepted", r)
	}
	es[0].Duration = 0
	if _, e := corech.Build(context.Background(), vs, es, []string{"A", "B"}, cfg(4)); e == nil {
		t.Fatal("nonpositive weight accepted")
	}
}
func FuzzCoreCHIndependent(f *testing.F) {
	for _, s := range []uint64{0, 1, 8, 91, 767} {
		f.Add(s)
	}
	f.Fuzz(func(t *testing.T, s uint64) {
		vs, es, ps, c := generated(s)
		x, e := corech.Build(context.Background(), vs, es, ps, c)
		if e != nil {
			t.Fatal(e)
		}
		inspect(t, vs, es, x, far)
	})
}

func TestDeclaredDegreeStopAndIsolatedComponent(t *testing.T) {
	vs := []string{"A", "X", "B"}
	es := []model.Footpath{edge("ax", "A", "X", 1), edge("xb", "X", "B", 1)}
	c := cfg(3)
	c.MaximumAverageCoreOutDegree = 0.5
	x, e := corech.Build(context.Background(), vs, es, []string{"A", "B"}, c)
	if e != nil || x.Stats().StopReason != "average_core_out_degree" || x.Stats().Contractions != 0 {
		t.Fatal(x.Stats(), e)
	}
	inspect(t, vs, es, x, far)
	c = cfg(3)
	x, e = corech.Build(context.Background(), vs, es, []string{"A", "B"}, c)
	if e != nil {
		t.Fatal(e)
	}
	before, e := x.SearchMany(context.Background(), "A", []string{"A", "B"}, 9, qcfg())
	if e != nil {
		t.Fatal(e)
	}
	vs = append(vs, "isolated0", "isolated1")
	es = append(es, edge("isolated", "isolated0", "isolated1", 1))
	c.MaxContractions = 9
	y, e := corech.Build(context.Background(), vs, es, []string{"A", "B"}, c)
	if e != nil {
		t.Fatal(e)
	}
	after, e := y.SearchMany(context.Background(), "A", []string{"A", "B"}, 9, qcfg())
	if e != nil {
		t.Fatal(e)
	}
	for i, p := range before.Paths {
		a := after.Paths[i]
		if a.Found != p.Found || a.Duration != p.Duration || !reflect.DeepEqual(a.RawEdges, p.RawEdges) {
			t.Fatal("isolated component changed answer", before, after)
		}
	}
	inspect(t, vs, es, y, far)
}
