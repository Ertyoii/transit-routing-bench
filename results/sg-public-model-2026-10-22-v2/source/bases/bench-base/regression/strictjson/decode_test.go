package strictjson_test

import (
	"github.com/ertyoii/transit-routing-go/strictjson"
	"testing"
)

func TestRejectNestedDuplicatesCaseAliasesAndTrailingGarbage(t *testing.T) {
	for _, s := range []string{`{"x":{"k":1,"k":2}}`, `{"x":{"k":1,"K":2}}`, `{"x":{"k":1,"\u006b":2}}`, `{"x":{"k":1}} garbage`, `{"x":{"k":1}} {}`} {
		var v struct {
			X struct {
				K int `json:"k"`
			} `json:"x"`
		}
		if e := strictjson.Decode([]byte(s), &v); e == nil {
			t.Fatalf("ambiguous input accepted: %s", s)
		}
	}
	var v []map[string]int
	if e := strictjson.Decode([]byte(`[{"k":1},{"k":2}]`), &v); e != nil || len(v) != 2 {
		t.Fatal("separate object keys must remain legal")
	}
}
