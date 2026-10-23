package internal
import(
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
// Producer has a streaming per-row parser. It never loads a Dataset or calls a
// routing algorithm. Row order/ID/multiplicity is retained in projection digests.
type graph struct{ids []string;index map[string]int;declared map[string]bool;edges []map[int]bool}
func newGraph()*graph{return &graph{index:map[string]int{},declared:map[string]bool{}}}
func(g *graph)intern(s string)(int,error){if s==""{return 0,fmt.Errorf("empty stop ID")};if i,ok:=g.index[s];ok{return i,nil};i:=len(g.ids);g.index[s]=i;g.ids=append(g.ids,s);g.edges=append(g.edges,nil);return i,nil}
func(g *graph)add(a,b string)error{i,e:=g.intern(a);if e!=nil{return e};j,e:=g.intern(b);if e!=nil{return e};if g.edges[i]==nil{g.edges[i]=map[int]bool{}};g.edges[i][j]=true;return nil}
func(g *graph)reachable(origin string,guard *Guard)([]string,error){start,ok:=g.index[origin];if !ok{return nil,fmt.Errorf("unknown origin")};seen:=make([]bool,len(g.ids));seen[start]=true;queue:=[]int{start};for h:=0;h<len(queue);h++{if e:=guard.Check();e!=nil{return nil,e};for to:=range g.edges[queue[h]]{if !seen[to]{seen[to]=true;queue=append(queue,to)}}};out:=make([]string,0,len(queue));for i,s:=range g.ids{if seen[i]{out=append(out,s)}};sort.Strings(out);return out,nil}
func streamProjection(path string,guard *Guard)(*graph,Projection,string,int64,error){
 var p Projection;f,e:=os.Open(path);if e!=nil{return nil,p,"",0,e};defer f.Close();stat,e:=f.Stat();if e!=nil{return nil,p,"",0,e};h:=sha256.New();d:=json.NewDecoder(io.TeeReader(guardedReader{f,guard},h));d.UseNumber();t,e:=d.Token();if e!=nil||t!=json.Delim('{'){return nil,p,"",0,fmt.Errorf("model must be an object")}
 g:=newGraph();fields:=map[string]bool{};ch,fh:=sha256.New(),sha256.New();ids:=map[string]map[string]bool{};for _,k:=range []string{"stops","trips","connections","footpaths","transfers"}{ids[k]=map[string]bool{}}
 for d.More(){if e=guard.Check();e!=nil{return nil,p,"",0,e};kt,e:=d.Token();if e!=nil{return nil,p,"",0,e};k,ok:=kt.(string);if !ok||fields[k]{return nil,p,"",0,fmt.Errorf("duplicate/invalid model key %q",k)};fields[k]=true
  var s shape;var count *uint64
  switch k{case "stops":s=stopShape;count=&p.Counts.Stops;case "trips":s=tripShape;count=&p.Counts.Trips;case "connections":s=connectionShape;count=&p.Counts.Connections;case "footpaths":s=footpathShape;count=&p.Counts.Footpaths;case "transfers":s=transferShape;count=&p.Counts.Transfers}
  if s==nil{var raw json.RawMessage;if e=d.Decode(&raw);e!=nil{return nil,p,"",0,e};switch k{case "schema_version","id","time_zone","service_date","data_kind":var v string;if e=json.Unmarshal(raw,&v);e!=nil||string(raw)=="null"{return nil,p,"",0,fmt.Errorf("invalid model scalar %s",k)};case "window":if e=checkObject(raw,shape{"start":"i","end":"i"});e!=nil{return nil,p,"",0,e};default:return nil,p,"",0,fmt.Errorf("unknown model field %s",k)};continue}
  tok,e:=d.Token();if e!=nil||tok!=json.Delim('['){return nil,p,"",0,fmt.Errorf("%s must be a complete array",k)}
  for d.More(){if e=guard.Row();e!=nil{return nil,p,"",0,e};var raw json.RawMessage;if e=d.Decode(&raw);e!=nil{return nil,p,"",0,e};if e=checkObject(raw,s);e!=nil{return nil,p,"",0,fmt.Errorf("%s row %d: %w",k,*count,e)}
   var id struct{ID string `json:"id"`;From string `json:"from"`;To string `json:"to"`};if e=json.Unmarshal(raw,&id);e!=nil{return nil,p,"",0,e};if id.ID==""||ids[k][id.ID]{return nil,p,"",0,fmt.Errorf("invalid/duplicate %s ID %q",k,id.ID)};ids[k][id.ID]=true
   switch k{case "stops":g.declared[id.ID]=true;if _,e=g.intern(id.ID);e!=nil{return nil,p,"",0,e};case "connections","footpaths":if e=g.add(id.From,id.To);e!=nil{return nil,p,"",0,e};line:=append(canonical([]any{k,*count,id.ID,id.From,id.To}),'\n');if k=="connections"{ch.Write(line)}else{fh.Write(line)}};*count++
  };tok,e=d.Token();if e!=nil||tok!=json.Delim(']'){return nil,p,"",0,fmt.Errorf("truncated %s",k)}
 };t,e=d.Token();if e!=nil||t!=json.Delim('}'){return nil,p,"",0,fmt.Errorf("truncated model")};if _,e=d.Token();e!=io.EOF{return nil,p,"",0,fmt.Errorf("trailing/extra JSON")}
 for _,k:=range []string{"schema_version","id","time_zone","service_date","stops","trips","connections","footpaths"}{if !fields[k]{return nil,p,"",0,fmt.Errorf("missing model field %s",k)}}
 if len(g.declared)==0{return nil,p,"",0,fmt.Errorf("empty stop table")};for _,s:=range g.ids{if !g.declared[s]{return nil,p,"",0,fmt.Errorf("edge references unknown stop %q",s)}}
 if e=guard.Check();e!=nil{return nil,p,"",0,e};p.ConnectionsSHA=hex.EncodeToString(ch.Sum(nil));p.FootpathsSHA=hex.EncodeToString(fh.Sum(nil));return g,p,hex.EncodeToString(h.Sum(nil)),stat.Size(),nil
}
func Produce(j Job,root,protocolSHA,frozenSHA string,guard *Guard)(Candidate,error){
 start:=time.Now();var c Candidate;q,e:=LoadQuery(j);if e!=nil{return c,e};g,p,sha,n,e:=streamProjection(j.Dataset,guard);if e!=nil{return c,e};if sha!=j.DatasetSHA{return c,fmt.Errorf("model full-byte SHA mismatch")};if !g.declared[q.Query.Origin]||!g.declared[q.Query.Destination]{return c,fmt.Errorf("invalid query endpoints")};r,e:=g.reachable(q.Query.Origin,guard);if e!=nil{return c,e};src,e:=sourceSHA(root,"producer.go");if e!=nil{return c,e};c=Candidate{Version:Version,DatasetSHA:sha,DatasetBytes:n,Query:q,Projection:p,ProducerSourceSHA:src,FrozenManifestSHA:frozenSHA,ProtocolSHA:protocolSHA,ElapsedSeconds:time.Since(start).Seconds()}
 i:=sort.SearchStrings(r,q.Query.Destination);if i<len(r)&&r[i]==q.Query.Destination{c.Kind="unknown_raw_graph_destination_reachable";c.Provenance="Raw superset graph reachability does not imply timetable feasibility, any journey, or any scalar optimum.";return c,nil}
 c.Kind="candidate_raw_graph_closed_cut_not_yet_verified";c.ClosedSet=r;c.ClosedSetSHA=SHA(canonical(r));c.Provenance="Producer-only raw directed stop graph BFS; all raw connection and footpath rows included with no temporal, pickup/dropoff, accessibility, rule, walking-role, or resource filtering. Not a qualified certificate until independent full-decode verification.";if e=guard.Check();e!=nil{return Candidate{},e};return c,nil
}
// Keep the schema import explicit as a static contract reference, never a router.
var _ schema.Query
