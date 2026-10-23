package main
import (
 "bytes"
 "crypto/sha256"
 "encoding/binary"
 "encoding/json"
 "math/rand/v2"
 "os"
 "path/filepath"
 "strconv"
 "testing"
 "github.com/ertyoii/transit-routing-bench/workloadseed"
)
// Test the REAL canonical ULTRA workload type and read function. No constructor
// or search is involved. Generic point-schema success is not this evidence.
func TestNativeULTRASeedParserSummaryAndRNG(t *testing.T) {
 for _,raw:=range []string{`0`,`9007199254740993`,`18446744073709551615`,`"phaseA-tune-seed"`} {
  body:=[]byte(`{"seed":`+raw+`,"method":"input-only","dataset_sha256":"bound","items":[]}`)
  path:=filepath.Join(t.TempDir(),"workload.json"); if e:=os.WriteFile(path,body,0600);e!=nil{t.Fatal(e)}
  var w workload; hash,e:=read(path,&w);if e!=nil{t.Fatal(raw,e)}
  after,_:=os.ReadFile(path);if !bytes.Equal(body,after)||hash==""{t.Fatal("read mutated original workload")}
  var scalar workloadseed.Seed;if e=json.Unmarshal([]byte(raw),&scalar);e!=nil{t.Fatal(e)}
  if w.Seed.Uint64()!=scalar.Uint64(){t.Fatal("wrong seed adapter")}
  expected:=uint64(0);if raw[0]!='"'{expected,e=strconv.ParseUint(raw,10,64);if e!=nil{t.Fatal(e)}};if raw[0]=='"'{sum:=sha256.Sum256([]byte(workloadseed.Domain+"phaseA-tune-seed"));expected=binary.BigEndian.Uint64(sum[:8]);if w.Seed.Metadata().SourceText!="phaseA-tune-seed"{t.Fatal("text provenance lost")}}
  a,b:=rand.NewPCG(w.Seed.Uint64(),17),rand.NewPCG(expected,17);for i:=0;i<16;i++{if a.Uint64()!=b.Uint64(){t.Fatal("RNG changed")}}
  summary,e:=json.Marshal(map[string]any{"seed":w.Seed,"seed_metadata":w.Seed.Metadata()});if e!=nil{t.Fatal(e)}
  var got struct{Seed uint64 `json:"seed"`;Meta workloadseed.Metadata `json:"seed_metadata"`};if e=json.Unmarshal(summary,&got);e!=nil||got.Seed!=expected||got.Meta.Uint64!=expected{t.Fatal("summary mapping",string(summary),e)}
  if raw[0]=='"'&&got.Meta.SourceKind!="text"{t.Fatal("summary dropped text kind")}
 }
 for _,raw:=range []string{`-1`,`1.0`,`1e2`,`null`,`true`,`""`,`"has space"`,`18446744073709551616`} {
  path:=filepath.Join(t.TempDir(),"bad.json");os.WriteFile(path,[]byte(`{"seed":`+raw+`,"method":"bad","dataset_sha256":"bound","items":[]}`),0600)
  var w workload;if _,e:=read(path,&w);e==nil{t.Fatal("invalid seed accepted",raw)}
 }
}
