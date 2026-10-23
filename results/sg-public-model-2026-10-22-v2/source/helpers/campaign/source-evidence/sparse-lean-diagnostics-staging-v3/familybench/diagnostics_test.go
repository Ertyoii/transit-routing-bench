package main

import (
	"context"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"testing"
 "strings"
	"github.com/ertyoii/transit-routing-bench/fixtures"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/ultra"
)
func sparseCostParity(t *testing.T,full ultra.SparsePreparation,cost ultra.SparseCostSummary) {
	t.Helper();f,c:=reflect.ValueOf(full),reflect.ValueOf(cost)
	for i:=0;i<f.NumField();i++ {name:=f.Type().Field(i).Name;if name=="Certificates" {continue};if !reflect.DeepEqual(f.Field(i).Interface(),c.FieldByName(name).Interface()) {t.Fatal("scalar cost mismatch",name)}}
	proofs:=0;for _,v:=range full.Certificates {proofs+=len(v.Proofs)}
	if cost.CertificateCount!=len(full.Certificates)||cost.ProofRecordCount!=proofs {t.Fatal("exact proof/certificate counts changed")}
}
func TestSparseDiagnosticsAdapterModesPreserveFullNativeOutput(t *testing.T) {
	b:=scopedFixture(t);cfg:=scopedInput(t,"ultra-subset")
	for _,name:=range []string{"ultra_cap_safe_stay_witness_subset_v1","ultra_subset_local_walk_ties"} {
		full,e:=prepareScopedDiagnostics(context.Background(),b.Dataset,name,cfg,"full");if e!=nil {t.Fatal(e)}
		lean,e:=prepareScopedDiagnostics(context.Background(),b.Dataset,name,cfg,"compact");if e!=nil {t.Fatal(e)}
		if !reflect.DeepEqual(full.config,lean.config)||full.fullCost!=nil||lean.fullCost==nil {t.Fatal("native config/evidence mode changed")}
		original:=full.cost().(ultra.SparsePreparation);compact,measurement:=measureDiagnostics(lean.cost)
		if !measurement.Enabled||measurement.ElapsedNS<0 {t.Fatal("prequery export clock missing")}
		sparseCostParity(t,original,compact.(ultra.SparseCostSummary))
		if !reflect.DeepEqual(original,lean.fullCost().(ultra.SparsePreparation)) {t.Fatal("full same-index evidence changed")}
		for _,q:=range b.Queries {a,c:=full.single(context.Background(),q),lean.single(context.Background(),q);if !reflect.DeepEqual(a,c) {t.Fatalf("diagnostic mode changed complete/raw/stats/error:%s",q.ID)}}
	}

}
func diagnosticsRecordProjection(v record) any {
	return struct{Raw []model.Journey;Final []model.Validated;Completed,Attempted,ValidEmpty,Transit bool;Status,Error string;Detail,Display,Quality,Certificates any}{v.Raw,v.Final,v.Completed,v.Attempted,v.ValidEmpty,v.Transit,v.Status,v.Error,v.Detail,v.Display,v.Quality,v.Certificates}
}
func TestSparseDiagnosticsProcessFullVersusCompactEvidenceParity(t *testing.T) {
	root,e:=filepath.Abs("../..");if e!=nil {t.Fatal(e)}
	binary:=filepath.Join(t.TempDir(),"familybench-sparse-lean-diagnostics")
	env:=append(os.Environ(),"GOTOOLCHAIN=local","GOWORK=off","GOPROXY=off","GOSUMDB=off","GOMAXPROCS=2")
	logSparseBuildAdmission(t,"before-test-sourcehash")
	hashCmd:=exec.Command("go","run","-buildvcs=false","-mod=vendor","./cmd/sourcehash");hashCmd.Dir,hashCmd.Env=root,env
    hashOut,e:=hashCmd.CombinedOutput();if e!=nil {t.Fatalf("source hash:%v\n%s",e,hashOut)}
    fingerprint:=strings.TrimSpace(string(hashOut))
    logSparseBuildAdmission(t,"before-test-build")
    build:=exec.Command("go","build","-buildvcs=false","-mod=vendor","-trimpath","-ldflags","-X github.com/ertyoii/transit-routing-bench/experiment.BuildSourceSHA256="+fingerprint,"-o",binary,"./cmd/familybench");build.Dir,build.Env=root,env
	if out,e:=build.CombinedOutput();e!=nil {t.Fatalf("source-bound build:%v\n%s",e,out)}
	for _,algorithm:=range []string{"ultra_cap_safe_stay_witness_subset_v1","ultra_subset_local_walk_ties"} {
		var control []record;var fullBefore,fullAfter ultra.SparsePreparation
		for _,mode:=range []string{"full","compact"} {
			out:=filepath.Join(t.TempDir(),"artifact")
			args:=[]string{"-fixture","testdata/scoped.manifest.json","-algorithm",algorithm,"-scoped-config","testdata/scoped-config/ultra-subset.json","-sparse-diagnostics",mode,"-warmups","0","-repetitions","1","-batch-size","1","-stream-responses","-out-dir",out}
			cmd:=exec.Command(binary,args...);cmd.Dir,cmd.Env=root,env
			if logs,e:=cmd.CombinedOutput();e!=nil {t.Fatalf("%s/%s:%v\n%s",algorithm,mode,e,logs)}
			read:=func(name string,v any){b,e:=os.ReadFile(filepath.Join(out,name));if e!=nil {t.Fatal(e)};if e=json.Unmarshal(b,v);e!=nil {t.Fatal(e)}}
			var p pass;read("pass-00.json",&p)
			var summary struct{Dataset string `json:"dataset_sha256"`;Scoped string `json:"scoped_configuration_sha256"`;Prep struct{Cost json.RawMessage `json:"index_cost_summary"`;Export diagnosticsExport `json:"diagnostics_export"`} `json:"preparation"`;Final json.RawMessage `json:"index_cost_final"`;FinalExport diagnosticsExport `json:"final_diagnostics_export"`;Evidence *fullDiagnosticsEvidence `json:"full_index_evidence"`}
			read("summary.json",&summary)
			if !summary.Prep.Export.Enabled||!summary.FinalExport.Enabled {t.Fatal("export phase instrumentation missing")}
			if mode=="full" {
				control=p.Records;json.Unmarshal(summary.Prep.Cost,&fullBefore);json.Unmarshal(summary.Final,&fullAfter)
				if summary.Evidence!=nil {t.Fatal("legacy full diagnostics unexpectedly deferred")}
			} else {
				if len(p.Records)!=len(control) {t.Fatal("offered denominator changed")}
				for i:=range p.Records {if !reflect.DeepEqual(diagnosticsRecordProjection(p.Records[i]),diagnosticsRecordProjection(control[i])) {t.Fatal("full/compact raw/final/native status/detail changed")}}
				var c0,c1 ultra.SparseCostSummary;json.Unmarshal(summary.Prep.Cost,&c0);json.Unmarshal(summary.Final,&c1);sparseCostParity(t,fullBefore,c0);sparseCostParity(t,fullAfter,c1)
				if summary.Evidence==nil {t.Fatal("full original evidence discarded")}
				var retained struct{Binding map[string]any `json:"binding"`;Preparation ultra.SparsePreparation `json:"preparation"`};read(summary.Evidence.File,&retained)
				if !reflect.DeepEqual(retained.Preparation,fullBefore)||retained.Binding["dataset_sha256"]!=summary.Dataset||retained.Binding["scoped_configuration_sha256"]!=summary.Scoped {t.Fatal("full same-index evidence identity/parity lost")}
				data,_:=os.ReadFile(filepath.Join(out,summary.Evidence.File));if fixtures.Sum(data)!=summary.Evidence.IO.SHA256||len(data)!=summary.Evidence.IO.Bytes {t.Fatal("full evidence content binding wrong")}
				var shape map[string]any;json.Unmarshal(summary.Prep.Cost,&shape);if _,ok:=shape["certificates"];ok {t.Fatal("compact prequery cost contains certificates")}
			}
		}
	}
}

// Compact mode is intentionally a no-op for non-Sparse native adapters. This
// common source preserves both original kernels and separately named local ties.
func TestSparseDiagnosticsCommonPrimaryRosterParity(t *testing.T) {
 b:=scopedFixture(t)
 for _,tc:=range []struct{name,config string}{{"trip_based_capped","tb"},{"trip_based_capped_answer_walk_ties","tb"},{"ultra_transfer_complete_capped","ultra-control"},{"ultra_capped_local_walk_ties","ultra-control"}} {
  full,e:=prepareScopedDiagnostics(context.Background(),b.Dataset,tc.name,scopedInput(t,tc.config),"full");if e!=nil {t.Fatal(tc.name,e)}
  lean,e:=prepareScopedDiagnostics(context.Background(),b.Dataset,tc.name,scopedInput(t,tc.config),"compact");if e!=nil {t.Fatal(tc.name,e)}
  if full.fullCost!=nil||lean.fullCost!=nil||!reflect.DeepEqual(full.config,lean.config)||!reflect.DeepEqual(full.cost(),lean.cost()) {t.Fatal("non-Sparse native diagnostics/config changed",tc.name)}
  for _,q:=range b.Queries {if !reflect.DeepEqual(full.single(context.Background(),q),lean.single(context.Background(),q)) {t.Fatal("non-Sparse raw/complete/native detail changed",tc.name,q.ID)}}
 }
 for _,name:=range []string{"raptor","raptor_early","raptor_local_walk_ties","raptor_early_local_walk_ties","mc_raptor","mc_raptor_early"} {
  // main keeps this exact original prepare branch regardless of diagnostics mode.
  a,e:=prepare(context.Background(),b.Dataset,name,10,10000,10000,1000000,10000);if e!=nil {t.Fatal(name,e)}
  c,e:=prepare(context.Background(),b.Dataset,name,10,10000,10000,1000000,10000);if e!=nil {t.Fatal(name,e)}
  if !reflect.DeepEqual(a.config,c.config) {t.Fatal("native runtime/caps changed",name)}
  for _,q:=range b.Queries {if !reflect.DeepEqual(a.single(context.Background(),q),c.single(context.Background(),q)) {t.Fatal("native point output changed",name,q.ID)}}
 }
}

func logSparseBuildAdmission(t *testing.T,stage string) {
 t.Helper();observed:=map[string]string{}
 for _,path:=range []string{"/proc/meminfo","/proc/self/limits","/proc/self/cgroup","/sys/fs/cgroup/memory.current","/sys/fs/cgroup/memory.max","/sys/fs/cgroup/memory.events"} {
  value,e:=os.ReadFile(path);if e!=nil {observed[path]="unavailable: "+e.Error()} else {observed[path]=string(value)}
 }
 t.Logf("actual memory/limits before %s: %+v",stage,observed)
 if dir:=os.Getenv("SPARSE_QUALIFICATION_EVIDENCE_DIR");dir!="" {
  payload,e:=json.MarshalIndent(observed,"","  ");if e!=nil {t.Fatal(e)}
  f,e:=os.OpenFile(filepath.Join(dir,stage+".json"),os.O_WRONLY|os.O_CREATE|os.O_EXCL,0600);if e!=nil {t.Fatal(e)}
  _,e=f.Write(append(payload,'\n'));ce:=f.Close();if e!=nil {t.Fatal(e)};if ce!=nil {t.Fatal(ce)}
 }
}
