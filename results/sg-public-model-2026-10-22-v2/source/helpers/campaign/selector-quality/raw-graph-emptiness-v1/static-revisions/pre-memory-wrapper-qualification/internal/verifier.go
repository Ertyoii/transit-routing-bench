package internal
import(
 "bytes"
 "crypto/sha256"
 "encoding/hex"
 "encoding/json"
 "fmt"
 "io"
 "os"
 "sort"
 "time"
 "rawgraphcert/schema"
)

// Independent decoder path: standard full Dataset decoding, never producer
// streaming, graph, BFS, router, adapted index, or emitted feasibility booleans.
func fullDecode(path string,guard *Guard)(schema.Dataset,string,int64,error){
 var m schema.Dataset;f,e:=os.Open(path);if e!=nil{return m,"",0,e};defer f.Close();st,e:=f.Stat();if e!=nil{return m,"",0,e};if st.Size()>128<<20{return m,"",0,fmt.Errorf("model exceeds frozen 128MiB input bound")};raw,e:=io.ReadAll(io.LimitReader(guardedReader{f,guard},st.Size()+1));if e!=nil{return m,"",0,e};if int64(len(raw))!=st.Size(){return m,"",0,fmt.Errorf("model changed size/truncated")}
 // The immutable raw byte buffer binds EVERY independent full-decode pass to
 // exactly the same bytes, without a reopen/TOCTOU projection escape.
 d:=json.NewDecoder(bytes.NewReader(raw));d.DisallowUnknownFields();if e=d.Decode(&m);e!=nil{return m,"",0,e};var extra any;if e=d.Decode(&extra);e!=io.EOF{return m,"",0,fmt.Errorf("extra/truncated JSON")};if e=guard.Check();e!=nil{return m,"",0,e};if e=verifyShapeBytes(raw,guard);e!=nil{return m,"",0,e};if e=m.Validate();e!=nil{return m,"",0,fmt.Errorf("native pure model validation: %w",e)};if e=guard.Check();e!=nil{return m,"",0,e};return m,SHA(raw),int64(len(raw)),nil
}
func verifyShapeBytes(raw []byte,guard *Guard)error{
 if e:=checkDuplicates(guardedReader{bytes.NewReader(raw),guard});e!=nil{return e};var top map[string]json.RawMessage;if e:=json.Unmarshal(raw,&top);e!=nil{return e};if top==nil{return fmt.Errorf("null model")}
 for _,k:=range []string{"schema_version","id","time_zone","service_date","stops","trips","connections","footpaths"}{if top[k]==nil{return fmt.Errorf("missing model field %s",k)}}
 for k,raw:=range top{if e:=guard.Check();e!=nil{return e};var s shape;switch k{case "stops":s=stopShape;case "trips":s=tripShape;case "connections":s=connectionShape;case "footpaths":s=footpathShape;case "transfers":s=transferShape;case "window":if e:=checkObject(raw,shape{"start":"i","end":"i"});e!=nil{return e};continue;default:if bytes.Equal(bytes.TrimSpace(raw),[]byte("null")){return fmt.Errorf("null model metadata %s",k)};continue}
  var rows []json.RawMessage;if e:=json.Unmarshal(raw,&rows);e!=nil{return e};if rows==nil{return fmt.Errorf("null model table %s",k)};for _,row:=range rows{if e:=guard.Check();e!=nil{return e};if e:=checkObject(row,s);e!=nil{return fmt.Errorf("%s shape: %w",k,e)}}
 };return nil
}
func Verify(j Job,root,protocolSHA,frozenSHA string,candidateRaw []byte,guard *Guard)(Verification,error){
 start:=time.Now();var out Verification;if e:=checkDuplicates(bytes.NewReader(candidateRaw));e!=nil{return out,e};var c Candidate;dec:=json.NewDecoder(bytes.NewReader(candidateRaw));dec.DisallowUnknownFields();if e:=dec.Decode(&c);e!=nil{return out,e};if c.Version!=Version||c.Kind!="candidate_raw_graph_closed_cut_not_yet_verified"||c.ProtocolSHA!=protocolSHA||c.FrozenManifestSHA!=frozenSHA{return out,fmt.Errorf("candidate kind/protocol/source mismatch")};ps,e:=sourceSHA(root,"producer.go");if e!=nil||ps!=c.ProducerSourceSHA{return out,fmt.Errorf("producer source mismatch")};q,e:=LoadQuery(j);if e!=nil{return out,e};if e=checkBinding(c.Query,q);e!=nil{return out,e}
 m,modelSHA,n,e:=fullDecode(j.Dataset,guard);if e!=nil{return out,e};if modelSHA!=j.DatasetSHA||modelSHA!=c.DatasetSHA||n!=c.DatasetBytes{return out,fmt.Errorf("full model byte binding mismatch")};if e=q.Query.Validate(m);e!=nil{return out,e};if q.Query.Origin==q.Query.Destination{return out,fmt.Errorf("origin==destination cannot prove empty")}
 if !sort.StringsAreSorted(c.ClosedSet)||len(c.ClosedSet)==0||SHA(canonical(c.ClosedSet))!=c.ClosedSetSHA{return out,fmt.Errorf("invalid sorted closed-set binding")};stops:=map[string]bool{};for _,s:=range m.Stops{stops[s.ID]=true};r:=map[string]bool{};for _,s:=range c.ClosedSet{if !stops[s]||r[s]{return out,fmt.Errorf("unknown/duplicate closed-set ID")};r[s]=true};if !r[q.Query.Origin]||r[q.Query.Destination]{return out,fmt.Errorf("closed-set endpoint condition fails")}
 // Independent exhaustive raw table loops. Even outside-R/duplicate endpoint
 // pairs count and hash once per original row; nothing is coalesced or filtered.
 p:=Projection{Counts:Counts{Stops:uint64(len(m.Stops)),Trips:uint64(len(m.Trips)),Connections:uint64(len(m.Connections)),Footpaths:uint64(len(m.Footpaths)),Transfers:uint64(len(m.Transfers))}};ch,fh:=sha256.New(),sha256.New();var nc,nf uint64
 for i,e:=range m.Connections{if er:=guard.Row();er!=nil{return out,er};if r[e.From]&&!r[e.To]{return out,fmt.Errorf("connection exits closed set: %s",e.ID)};a:=[]any{"connections",uint64(i),e.ID,e.From,e.To};line:=canonical(a);ch.Write(line);ch.Write([]byte{10});nc++}
 for i,e:=range m.Footpaths{if er:=guard.Row();er!=nil{return out,er};if r[e.From]&&!r[e.To]{return out,fmt.Errorf("footpath exits closed set: %s",e.ID)};a:=[]any{"footpaths",uint64(i),e.ID,e.From,e.To};line:=canonical(a);fh.Write(line);fh.Write([]byte{10});nf++}
 p.ConnectionsSHA=hex.EncodeToString(ch.Sum(nil));p.FootpathsSHA=hex.EncodeToString(fh.Sum(nil));if !bytes.Equal(canonical(p),canonical(c.Projection))||nc!=p.Counts.Connections||nf!=p.Counts.Footpaths{return out,fmt.Errorf("exhaustive raw edge counts/projection mismatch")};if e=guard.Check();e!=nil{return out,e};vs,e:=sourceSHA(root,"verifier.go");if e!=nil{return out,e}
 out=Verification{Version:Version,Kind:"proven_empty_by_raw_stop_superset",ModelRelative:true,DatasetSHA:modelSHA,QueryCanonicalSHA:q.CanonicalSHA,CandidateSHA:SHA(candidateRaw),IndependentlyScanned:p,RawConnectionClosureRows:nc,RawFootpathClosureRows:nf,VerifierSourceSHA:vs,FrozenManifestSHA:frozenSHA,Proof:"Origin belongs to the checked closed set, destination does not, and every raw connection and directed raw footpath out of the set stays inside. Every accepted finite-model journey induces a path in this unfiltered movement superset. Thus no finite-model journey exists for any preference. This is not a statement about physical or full real-world reachability.",OriginalSlotsUnchanged:true,AppliesRegardlessPreference:true,DirectScalarExecutions:0,ElapsedSeconds:time.Since(start).Seconds()};return out,nil
}
