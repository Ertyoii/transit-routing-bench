package experiment_test

import (
	"github.com/ertyoii/transit-routing-bench/experiment"
	"os"
	"path/filepath"
	"testing"
)

func TestRoutingPinRejectsChangedExtraOrMissingFiles(t *testing.T) {
	lock, e := experiment.VerifyRoutingLock("..")
	if e != nil {
		t.Fatal(e)
	}
	root := t.TempDir()
	copyFile := func(rel string) {
		t.Helper()
		b, e := os.ReadFile(filepath.Join("..", rel))
		if e != nil {
			t.Fatal(e)
		}
		p := filepath.Join(root, rel)
		if e = os.MkdirAll(filepath.Dir(p), 0700); e != nil {
			t.Fatal(e)
		}
		if e = os.WriteFile(p, b, 0600); e != nil {
			t.Fatal(e)
		}
	}
	for _, name := range []string{"go.mod", "routing.lock.json", "vendor/modules.txt"} {
		copyFile(name)
	}
	for name := range lock.Files {
		copyFile("vendor/" + lock.Module + "/" + name)
	}
	if _, e = experiment.VerifyRoutingLock(root); e != nil {
		t.Fatal(e)
	}
	rel := "vendor/" + lock.Module + "/model/model.go"
	path := filepath.Join(root, rel)
	if e = os.WriteFile(path, []byte("changed"), 0600); e != nil {
		t.Fatal(e)
	}
	if _, e = experiment.VerifyRoutingLock(root); e == nil {
		t.Fatal("changed vendor accepted")
	}
	copyFile(rel)
	if e = os.Remove(path); e != nil {
		t.Fatal(e)
	}
	if _, e = experiment.VerifyRoutingLock(root); e == nil {
		t.Fatal("missing vendor accepted")
	}
	copyFile(rel)
	if e = os.WriteFile(filepath.Join(root, "vendor", lock.Module, "injected.go"), []byte("package injected"), 0600); e != nil {
		t.Fatal(e)
	}
	if _, e = experiment.VerifyRoutingLock(root); e == nil {
		t.Fatal("extra vendor accepted")
	}
}
