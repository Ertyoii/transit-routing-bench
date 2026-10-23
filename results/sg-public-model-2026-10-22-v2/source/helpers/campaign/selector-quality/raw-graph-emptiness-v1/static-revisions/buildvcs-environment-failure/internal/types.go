// Package internal contains a one-sided, finite-model raw-graph certificate lane.
// It imports no routing, CSA, scalar-oracle, checker, or contributor code.
package internal

import (
 "bytes"
 "crypto/sha256"
 "encoding/base64"
 "encoding/hex"
 "encoding/json"
 "fmt"
 "io"
 "os"
 "path/filepath"
 "time"
 "rawgraphcert/schema"
)

const Version = "raw-graph-closed-cut-v1"
const MaxSecond int64 = 604800

type Job struct {
 Window string `json:"window"`
 Dataset string `json:"dataset"`
 DatasetSHA string `json:"dataset_sha256"`
 Queries string `json:"queries"`
 QueriesSHA string `json:"queries_sha256"`
 QueryID string `json:"query_id"`
 QuerySHA string `json:"query_canonical_sha256"`
 OriginalSlots int `json:"original_unknown_slots"`
}
type Recipe struct {
 Version string `json:"version"`
 Scope string `json:"scope"`
 ProtocolSHA string `json:"protocol_sha256"`
 Jobs []Job `json:"jobs"`
}
type Counts struct {
 Stops uint64 `json:"stops"`
 Trips uint64 `json:"trips"`
 Connections uint64 `json:"connections"`
 Footpaths uint64 `json:"footpaths"`
 Transfers uint64 `json:"transfers"`
}
type Projection struct {
 Counts Counts `json:"raw_table_counts"`
 ConnectionsSHA string `json:"connections_projection_sha256"`
 FootpathsSHA string `json:"footpaths_projection_sha256"`
}
type QueryBinding struct {
 SourceSHA string `json:"source_file_sha256"`
 RawBase64 string `json:"query_exact_bytes_base64"`
 RawSHA string `json:"query_exact_bytes_sha256"`
 CanonicalSHA string `json:"query_canonical_sha256"`
 Query schema.Query `json:"query"`
}
type Candidate struct {
 Version string `json:"version"`
 Kind string `json:"kind"`
 DatasetSHA string `json:"dataset_sha256"`
 DatasetBytes int64 `json:"dataset_bytes"`
 Query QueryBinding `json:"query_binding"`
 Projection Projection `json:"projection"`
 ClosedSet []string `json:"closed_set_sorted_stop_ids"`
 ClosedSetSHA string `json:"closed_set_sha256"`
 ProducerSourceSHA string `json:"producer_source_sha256"`
 FrozenManifestSHA string `json:"frozen_manifest_sha256"`
 ProtocolSHA string `json:"protocol_sha256"`
 Provenance string `json:"provenance"`
 ElapsedSeconds float64 `json:"elapsed_seconds"`
}
type Verification struct {
 Version string `json:"version"`
 Kind string `json:"kind"`
 ModelRelative bool `json:"finite_supplied_model_only"`
 DatasetSHA string `json:"dataset_sha256"`
 QueryCanonicalSHA string `json:"query_canonical_sha256"`
 CandidateSHA string `json:"candidate_file_sha256"`
 IndependentlyScanned Projection `json:"independently_scanned"`
 RawConnectionClosureRows uint64 `json:"connection_rows_checked_for_closure"`
 RawFootpathClosureRows uint64 `json:"footpath_rows_checked_for_closure"`
 VerifierSourceSHA string `json:"verifier_source_sha256"`
 FrozenManifestSHA string `json:"frozen_manifest_sha256"`
 Proof string `json:"proof"`
 OriginalSlotsUnchanged bool `json:"original_scalar_slots_unchanged"`
 AppliesRegardlessPreference bool `json:"applies_independently_of_preference"`
 DirectScalarExecutions int `json:"direct_scalar_executions"`
 ElapsedSeconds float64 `json:"elapsed_seconds"`
}
func SHA(b []byte) string { x:=sha256.Sum256(b); return hex.EncodeToString(x[:]) }
func canonical(v any) []byte { var b bytes.Buffer; e:=json.NewEncoder(&b); e.SetEscapeHTML(false); if err:=e.Encode(v);err!=nil { panic(err) }; return bytes.TrimSuffix(b.Bytes(),[]byte("\n")) }
func canonicalRaw(b []byte) ([]byte,error) { var x any; d:=json.NewDecoder(bytes.NewReader(b));d.UseNumber(); if err:=d.Decode(&x);err!=nil{return nil,err};return canonical(x),nil }
func writeNew(path string, v any) error { f,e:=os.OpenFile(path,os.O_CREATE|os.O_EXCL|os.O_WRONLY,0644);if e!=nil{return e};b:=append(canonical(v),'\n');_,e=f.Write(b);ce:=f.Close();if e!=nil{return e};return ce }
func loadSmall(path string, max int64) ([]byte,error) { f,e:=os.Open(path);if e!=nil{return nil,e};defer f.Close();b,e:=io.ReadAll(io.LimitReader(f,max+1));if e!=nil{return nil,e};if int64(len(b))>max{return nil,fmt.Errorf("small binding exceeds limit")};return b,nil }
func LoadRecipe(path, window string)(Recipe,Job,error) { var r Recipe;b,e:=loadSmall(path,1<<20);if e!=nil{return r,Job{},e};if e=checkDuplicates(bytes.NewReader(b));e!=nil{return r,Job{},e};d:=json.NewDecoder(bytes.NewReader(b));d.DisallowUnknownFields();if e=d.Decode(&r);e!=nil{return r,Job{},e};if r.Version!=Version||r.Scope!="exactly_two_original_unknown_tune_queries"||len(r.Jobs)!=2{return r,Job{},fmt.Errorf("invalid campaign scope")};for _,j:=range r.Jobs { if j.Window==window {if j.OriginalSlots!=9{return r,j,fmt.Errorf("invalid original-slot binding")};return r,j,nil} };return r,Job{},fmt.Errorf("unfrozen query/window") }
func LoadQuery(j Job)(QueryBinding,error) {
 var out QueryBinding;b,e:=loadSmall(j.Queries,1<<20);if e!=nil{return out,e};if SHA(b)!=j.QueriesSHA{return out,fmt.Errorf("query source SHA mismatch")};if e=checkDuplicates(bytes.NewReader(b));e!=nil{return out,e}
 var w struct { DatasetSHA string `json:"dataset_sha256"`;Items []struct{Query json.RawMessage `json:"query"`} `json:"items"` }
 if e=json.Unmarshal(b,&w);e!=nil{return out,e};if w.DatasetSHA!=j.DatasetSHA||len(w.Items)!=1{return out,fmt.Errorf("singleton/model query binding mismatch")};raw:=w.Items[0].Query
 if e=checkQueryShape(raw);e!=nil{return out,e};if e=json.Unmarshal(raw,&out.Query);e!=nil{return out,e};c,e:=canonicalRaw(raw);if e!=nil{return out,e};if out.Query.ID!=j.QueryID||SHA(c)!=j.QuerySHA{return out,fmt.Errorf("query identity/canonical SHA mismatch")};if out.Query.Origin==out.Query.Destination{return out,fmt.Errorf("origin==destination is ineligible for emptiness")}
 out.SourceSHA=SHA(b);out.RawBase64=base64.StdEncoding.EncodeToString(raw);out.RawSHA=SHA(raw);out.CanonicalSHA=SHA(c);return out,nil
}
func checkBinding(actual, expected QueryBinding) error {if !bytes.Equal(canonical(actual),canonical(expected)){return fmt.Errorf("exact query binding mismatch")};return nil}
func sourceSHA(root, name string)(string,error){b,e:=os.ReadFile(filepath.Join(root,"internal",name));if e!=nil{return "",e};return SHA(b),nil}
func frozen(root string)(string,error){b,e:=loadSmall(filepath.Join(root,"FROZEN.json"),2<<20);if e!=nil{return "",e};var m struct{Files map[string]string `json:"files"`};if e=json.Unmarshal(b,&m);e!=nil{return "",e};if len(m.Files)<8{return "",fmt.Errorf("incomplete freeze manifest")};for p,want:=range m.Files{if filepath.IsAbs(p)||filepath.Clean(p)!=p||p==".."||len(p)>3&&p[:3]=="../"{return "",fmt.Errorf("unsafe frozen path")};bb,e:=os.ReadFile(filepath.Join(root,p));if e!=nil{return "",e};if SHA(bb)!=want{return "",fmt.Errorf("source/protocol freeze mismatch: %s",p)}};return SHA(b),nil}
type Guard struct{ Deadline time.Time; Rows uint64; MaxRows uint64 }
func(g *Guard) Check()error{if !g.Deadline.IsZero()&&!time.Now().Before(g.Deadline){return fmt.Errorf("budget exhausted: deadline before complete certificate")};return nil}
func(g *Guard) Row()error{g.Rows++;if g.MaxRows>0&&g.Rows>g.MaxRows{return fmt.Errorf("budget exhausted: raw rows")};return g.Check()}
type guardedReader struct{ r io.Reader;g *Guard }
func(r guardedReader)Read(b []byte)(int,error){if e:=r.g.Check();e!=nil{return 0,e};return r.r.Read(b)}
