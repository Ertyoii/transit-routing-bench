package fixtures_test

import (
	"bytes"
	"encoding/json"
	"github.com/ertyoii/transit-routing-bench/fixtures"
	"os"
	"path/filepath"
	"testing"
)

func TestPinnedFixtureAndTampering(t *testing.T) {
	_, m, e := fixtures.Load("../testdata/tiny.manifest.json")
	if e != nil {
		t.Fatal(e)
	}
	dir := t.TempDir()
	for _, name := range []string{"tiny.manifest.json", m.DataFile, m.LicenseFile} {
		b, e := os.ReadFile(filepath.Join("../testdata", name))
		if e != nil {
			t.Fatal(e)
		}
		if e = os.WriteFile(filepath.Join(dir, name), b, 0600); e != nil {
			t.Fatal(e)
		}
	}
	p := filepath.Join(dir, m.DataFile)
	if e = os.WriteFile(p, []byte("{}"), 0600); e != nil {
		t.Fatal(e)
	}
	if _, _, e = fixtures.Load(filepath.Join(dir, "tiny.manifest.json")); e == nil {
		t.Fatal("tampered data accepted")
	}
	// A valid hash must not permit unknown semantics to pass the strict parser.
	b := []byte(`{"dataset":{},"queries":[],"frequencies_are_exact":true}`)
	if e = os.WriteFile(p, b, 0600); e != nil {
		t.Fatal(e)
	}
	m.DataSHA256 = fixtures.Sum(b)
	mb, e := json.Marshal(m)
	if e != nil {
		t.Fatal(e)
	}
	if e = os.WriteFile(filepath.Join(dir, "tiny.manifest.json"), mb, 0600); e != nil {
		t.Fatal(e)
	}
	if _, _, e = fixtures.Load(filepath.Join(dir, "tiny.manifest.json")); e == nil {
		t.Fatal("unsupported field accepted")
	}
}

func TestDuplicateJSONConstraintRejected(t *testing.T) {
	data, e := os.ReadFile("../testdata/tiny.json")
	if e != nil {
		t.Fatal(e)
	}
	_, m, e := fixtures.Load("../testdata/tiny.manifest.json")
	if e != nil {
		t.Fatal(e)
	}
	data = bytes.Replace(data, []byte(`"max_walk_seconds":10`), []byte(`"max_walk_seconds":0,"max_walk_seconds":10`), 1)
	m.DataSHA256 = fixtures.Sum(data)
	mb, e := json.Marshal(m)
	if e != nil {
		t.Fatal(e)
	}
	dir := t.TempDir()
	license, e := os.ReadFile("../testdata/" + m.LicenseFile)
	if e != nil {
		t.Fatal(e)
	}
	for name, content := range map[string][]byte{m.DataFile: data, m.LicenseFile: license, "manifest.json": mb} {
		if e = os.WriteFile(filepath.Join(dir, name), content, 0600); e != nil {
			t.Fatal(e)
		}
	}
	if _, _, e = fixtures.Load(filepath.Join(dir, "manifest.json")); e == nil {
		t.Fatal("contradictory duplicate constraint accepted")
	}
}
