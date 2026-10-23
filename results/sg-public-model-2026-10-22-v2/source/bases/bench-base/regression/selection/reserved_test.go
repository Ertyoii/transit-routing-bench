package selection_test

import (
	"fmt"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/selection"
	"testing"
)

func TestReservationRetainsLaterLowerTransferOption(t *testing.T) {
	pool := []model.Validated{{Identity: "lower-transfer", Metrics: model.Metrics{Arrival: 28143, Boardings: 2, Transfers: 1, LegCount: 2}}}
	for i := 0; i < 12; i++ {
		pool = append(pool, model.Validated{Identity: fmt.Sprintf("early-%02d", i), Metrics: model.Metrics{Arrival: 27885 + int64(i), Boardings: 3, Transfers: 2, LegCount: 3}})
	}
	plain, err := selection.Select(pool, false, selection.Spec{Mode: selection.Candidates, CandidateCap: 10})
	if err != nil {
		t.Fatal(err)
	}
	for _, v := range plain.Journeys {
		if v.Identity == "lower-transfer" {
			t.Fatal("fixture did not lose lower-transfer option")
		}
	}
	reserved, err := selection.ReserveArrivalBoarding(pool, 10)
	if err != nil || len(reserved.Journeys) != 10 || reserved.Exact || !reserved.Capped {
		t.Fatalf("bad candidate contract: %+v %v", reserved, err)
	}
	found := false
	for _, v := range reserved.Journeys {
		found = found || v.Identity == "lower-transfer"
	}
	if !found {
		t.Fatal("reserved set lost lower-transfer option")
	}
	if _, err = selection.ReserveArrivalBoarding(pool, 1); err == nil {
		t.Fatal("insufficient frontier budget silently accepted")
	}
}
