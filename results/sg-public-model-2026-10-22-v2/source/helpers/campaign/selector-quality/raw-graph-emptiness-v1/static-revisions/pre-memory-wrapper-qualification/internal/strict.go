package internal
import("bytes";"encoding/json";"fmt";"io")

// Only duplicate detection is shared with the full-decode verifier. The verifier's
// table membership/counts/closure never depend on this token walk or the producer.
func checkDuplicates(r io.Reader)error{d:=json.NewDecoder(r);d.UseNumber();if e:=duplicateValue(d);e!=nil{return e};if _,e:=d.Token();e!=io.EOF{return fmt.Errorf("trailing/extra JSON: %v",e)};return nil}
func duplicateValue(d *json.Decoder)error{t,e:=d.Token();if e!=nil{return e};x,ok:=t.(json.Delim);if !ok{return nil};switch x{case '{':seen:=map[string]bool{};for d.More(){k,e:=d.Token();if e!=nil{return e};s,ok:=k.(string);if !ok||seen[s]{return fmt.Errorf("duplicate/non-string object field %q",s)};seen[s]=true;if e=duplicateValue(d);e!=nil{return e}};t,e=d.Token();if e!=nil||t!=json.Delim('}'){return fmt.Errorf("unterminated object")};case '[':for d.More(){if e=duplicateValue(d);e!=nil{return e}};t,e=d.Token();if e!=nil||t!=json.Delim(']'){return fmt.Errorf("unterminated array")};default:return fmt.Errorf("unexpected delimiter")};return nil}
type shape map[string]string
var stopShape=shape{"id":"s","accessible":"s","parent_station":"?s","location_type":"?i"}
var tripShape=shape{"id":"s","accessible":"s","source_id":"?s","route_id":"?s","service_date":"?s"}
var connectionShape=shape{"id":"s","trip_id":"s","sequence":"i","from":"s","to":"s","departure":"i","arrival":"i","pickup":"b","dropoff":"b"}
var footpathShape=shape{"id":"s","from":"s","to":"s","duration":"i","accessible":"s","provenance":"?s"}
var transferShape=shape{"id":"s","from_stop":"s","to_stop":"s","from_trip":"?s","to_trip":"?s","from_route":"?s","to_route":"?s","type":"i","min_seconds":"i"}
var queryShape=shape{"id":"s","origin":"s","destination":"s","departure":"i","latest_arrival":"i","transfer_buffer":"i","max_walk_seconds":"i","max_boardings":"i","max_legs":"i","accessible_only":"b","walking_limits":"?w"}
func checkObject(raw []byte,s shape)error{if e:=checkDuplicates(bytes.NewReader(raw));e!=nil{return e};if len(bytes.TrimSpace(raw))==0||bytes.TrimSpace(raw)[0]!='{'{return fmt.Errorf("expected object")};var o map[string]json.RawMessage;if e:=json.Unmarshal(raw,&o);e!=nil{return e};for k,t:=range s{if t[0]!='?'&&o[k]==nil{return fmt.Errorf("missing field %s",k)}};for k,v:=range o{t,ok:=s[k];if !ok{return fmt.Errorf("unknown field %s",k)};if t[0]=='?'{t=t[1:]};v=bytes.TrimSpace(v);if bytes.Equal(v,[]byte("null")){return fmt.Errorf("null field %s",k)};switch t{case "s":var x string;if e:=json.Unmarshal(v,&x);e!=nil{return fmt.Errorf("%s not string",k)};case "i":var x int64;if e:=json.Unmarshal(v,&x);e!=nil{return fmt.Errorf("%s not integer",k)};case "b":var x bool;if e:=json.Unmarshal(v,&x);e!=nil{return fmt.Errorf("%s not bool",k)};case "w":if e:=checkObject(v,shape{"access_seconds":"i","egress_seconds":"i","transfer_seconds":"i","direct_seconds":"i"});e!=nil{return e};default:return fmt.Errorf("unknown type")}};return nil}
func checkQueryShape(raw []byte)error{return checkObject(raw,queryShape)}
