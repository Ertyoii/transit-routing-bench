package regression

// STATIC STAGING ONLY: lean serving adapter qualification on a tiny literal model.
import (
 "context"
 "fmt"
 "testing"

 "github.com/ertyoii/transit-routing-go/model"
 "github.com/ertyoii/transit-routing-go/recommend"
 "github.com/ertyoii/transit-routing-go/validate"
)
func safeServingConfig(objective string)recommend.ChoiceConfig{
 prefs:=[]recommend.Preference{};for _,t:=range []int64{0,150,300,600,900}{for _,w:=range []int64{0,1,2,4}{prefs=append(prefs,recommend.Preference{ID:fmt.Sprintf("t%d_w%d",t,w),TransferSeconds:t,ExtraWalkWeight:w})}}
 baseline:=recommend.ChoiceConfig{MaxCandidates:1024,MaxSubsets:200000,LeanDelivery:true,DeliveryPolicy:"finite_preferences_v2",DeliveryLimits:[]int{3},Groups:[]recommend.PreferenceGroup{{Name:"explicit_twenty_hypotheses",Preferences:prefs}}}
 safe:=&recommend.FiniteSafeConfig{Baseline:baseline,MaxCandidates:64,MaxStates:200000,Domain:recommend.BoundedConfig{MinTransfer:0,MaxTransfer:900,MinWalk:0,MaxWalk:4,Objective:objective,Limits:[]int{3},Exact:true,MaxCriticalPoints:100000,MaxWork:50000000,MaxMatrixBytes:67108864}}
 return recommend.ChoiceConfig{MaxCandidates:64,MaxSubsets:200000,LeanDelivery:true,DeliveryPolicy:"finite20_safe_v1",DeliveryLimits:[]int{3},FiniteSafe:safe}
}
func TestFiniteSafeLeanServingUsesCheckerSnapshotAndRejectsLegacyIndex(t *testing.T){
 d:=model.Dataset{SchemaVersion:"0.2",ID:"safe-lean-toy",TimeZone:"Asia/Singapore",ServiceDate:"2026-10-20",Stops:[]model.Stop{{ID:"a",Accessible:model.Yes},{ID:"b",Accessible:model.Yes}},Trips:[]model.Trip{{ID:"t",RouteID:"r",Accessible:model.Yes}},Connections:[]model.Connection{{ID:"c",TripID:"t",Sequence:0,From:"a",To:"b",Departure:10,Arrival:20,Pickup:true,Dropoff:true}},Footpaths:[]model.Footpath{}}
 checker,err:=validate.New(d);if err!=nil{t.Fatal(err)};lean,err:=recommend.NewBoundedFromChecker(checker);if err!=nil{t.Fatal(err)}
 q:=model.Query{ID:"q",Origin:"a",Destination:"b",Departure:0,LatestArrival:100,MaxBoardings:1,MaxLegs:3};j:=model.Journey{Legs:[]model.Leg{{Kind:"ride",Ref:"c",Departure:10,Arrival:20}}}
 d.Connections[0].Arrival=50 // Must not mutate the checker's private model snapshot.
 for _,objective:=range []string{"absolute","normalized"}{cfg:=safeServingConfig(objective);out,e:=lean.EvaluateChoices(context.Background(),q,[]model.Journey{j},cfg);if e!=nil||out.FiniteSafeChoices==nil||!out.FiniteSafeChoices.Complete||len(out.Features)!=1||out.Features[0].Duration!=20||out.ContinuousChoices!=nil||out.Choices!=nil||len(out.Selections)!=0{t.Fatalf("lean safe route changed or controls leaked: %+v %v",out,e)}}
 legacy,err:=recommend.New(d);if err!=nil{t.Fatal(err)};if _,err=legacy.EvaluateChoices(context.Background(),q,[]model.Journey{j},safeServingConfig("absolute"));err==nil{t.Fatal("legacy recovery constructor silently accepted safe serving config")}
 cfg:=safeServingConfig("absolute");cfg.DeliveryLimits=[]int{5};if _,err=lean.EvaluateChoices(context.Background(),q,[]model.Journey{j},cfg);err==nil{t.Fatal("wrong requested limit accepted")}
}
