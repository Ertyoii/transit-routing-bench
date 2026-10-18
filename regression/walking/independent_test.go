package walking_test

import (
	"context"
	"fmt"
	"github.com/ertyoii/transit-routing-go/walking"
	"github.com/ertyoii/transit-routing-go/walking/graph"
	"math/rand"
	"testing"
)

// Floyd-Warshall uses a dense independent recurrence, no production search/pruning.
// Every generated graph is bounded; all ordered pairs (including disconnected) are checked.
func independent(t *testing.T, seed int64) {
	t.Helper()
	rng := rand.New(rand.NewSource(seed))
	const n = 7
	const infinity = int64(1 << 50)
	d := graph.Data{Descriptor: walking.Descriptor{ProviderID: "independent-fixture", GraphID: fmt.Sprint(seed), Version: "1", CostModel: "seconds", RoleIndependent: true}}
	for i := 0; i < n; i++ {
		access := walking.Yes
		if rng.Intn(4) == 0 {
			access = walking.Unknown
		}
		d.Nodes = append(d.Nodes, graph.Node{ID: fmt.Sprint(i), Accessible: access})
	}
	type edge struct {
		a, b       int
		cost       int64
		accessible bool
	}
	edges := []edge{}
	for a := 0; a < n; a++ {
		for b := 0; b < n; b++ {
			if a == b || rng.Intn(3) != 0 {
				continue
			}
			e := edge{a, b, int64(1 + rng.Intn(8)), rng.Intn(4) != 0}
			edges = append(edges, e)
			access := walking.Yes
			if !e.accessible {
				access = walking.Unknown
			}
			id := fmt.Sprintf("%d/%d", a, b)
			d.Edges = append(d.Edges, walking.Segment{ID: id, From: fmt.Sprint(a), To: fmt.Sprint(b), Seconds: e.cost, Accessible: access, Witness: walking.Witness{Source: "generated", Revision: fmt.Sprint(seed), EdgeIDs: []string{id}}})
		}
	}
	g, e := graph.New(d, graph.DefaultLimits())
	if e != nil {
		t.Fatal(e)
	}
	for _, accessible := range []bool{false, true} {
		for _, absorbing := range []int{-1, 3} {
			var dist [n][n]int64
			for i := 0; i < n; i++ {
				for j := 0; j < n; j++ {
					if i != j {
						dist[i][j] = infinity
					}
				}
			}
			for _, e := range edges {
				if e.a == absorbing || accessible && (!e.accessible || d.Nodes[e.a].Accessible != walking.Yes || d.Nodes[e.b].Accessible != walking.Yes) {
					continue
				}
				dist[e.a][e.b] = min(dist[e.a][e.b], e.cost)
			}
			for k := 0; k < n; k++ {
				for i := 0; i < n; i++ {
					for j := 0; j < n; j++ {
						dist[i][j] = min(dist[i][j], dist[i][k]+dist[k][j])
					}
				}
			}
			for _, bound := range []int64{0, 5, 30} {
				for a := 0; a < n; a++ {
					for b := 0; b < n; b++ {
						r := walking.Request{SnapshotID: g.Descriptor().SnapshotID, From: walking.Endpoint{NodeID: fmt.Sprint(a)}, To: walking.Endpoint{NodeID: fmt.Sprint(b)}, Options: walking.Options{Role: walking.Direct, MaxSeconds: bound, AccessibleOnly: accessible}}
						if absorbing >= 0 {
							r.Options.StopAt = fmt.Sprint(absorbing)
						}
						v, e := g.Route(context.Background(), r)
						if e != nil {
							t.Fatal(e)
						}
						if dist[a][b] > bound {
							if v.Status != walking.Unreachable || v.Path != nil {
								t.Fatalf("seed %d unexpected path %d/%d", seed, a, b)
							}
						} else {
							if v.Path == nil || v.Path.Seconds != dist[a][b] {
								t.Fatalf("seed %d wrong distance %d/%d: %+v want %d", seed, a, b, v, dist[a][b])
							}
							if e = g.ValidatePath(r, v); e != nil {
								t.Fatal(e)
							}
						}
					}
				}
			}
		}
	}
}
func TestIndependentDirectedClosures(t *testing.T) {
	for seed := int64(0); seed < 40; seed++ {
		independent(t, seed)
	}
}
func FuzzWalkingProvider(f *testing.F) {
	f.Add(int64(0))
	f.Add(int64(17))
	f.Fuzz(func(t *testing.T, seed int64) { independent(t, seed) })
}
