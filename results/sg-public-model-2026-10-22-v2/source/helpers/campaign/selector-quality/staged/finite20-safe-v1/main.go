package main

// Offline feature-only qualification CLI. Not a routing/serving endpoint.
import (
 "context"
 "encoding/json"
 "fmt"
 "io"
 "os"

 "github.com/ertyoii/transit-routing-bench/experiment"
 "github.com/ertyoii/transit-routing-go/recommend"
)
func main(){
 dec:=json.NewDecoder(os.Stdin);dec.DisallowUnknownFields();enc:=json.NewEncoder(os.Stdout);seen:=map[string]bool{}
 for {
  var request struct{ID string `json:"request_id"`;Features []recommend.Feature `json:"features"`;Config recommend.FiniteSafeConfig `json:"config"`}
  err:=dec.Decode(&request);if err==io.EOF{return};if err!=nil{fmt.Fprintln(os.Stderr,err);os.Exit(2)}
  if request.ID==""||seen[request.ID]{fmt.Fprintln(os.Stderr,"duplicate/empty request ID");os.Exit(2)};seen[request.ID]=true
  result,err:=recommend.SelectFiniteSafe(context.Background(),request.Features,request.Config);message:="";if err!=nil{message=err.Error()}
  if err=enc.Encode(map[string]any{"request_id":request.ID,"result":result,"error":message,"build_source_sha256":experiment.BuildSourceSHA256});err!=nil{fmt.Fprintln(os.Stderr,err);os.Exit(2)}
 }
}
