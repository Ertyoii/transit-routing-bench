package internal
import(
 "encoding/json"
 "flag"
 "fmt"
 "os"
 "path/filepath"
 "runtime"
 "runtime/debug"
 "strconv"
 "strings"
 "syscall"
 "time"
)
const globalLock="/workspace/shared/sg-coldstart/setup/campaign.lock"
const MiB=uint64(1<<20)
func memoryAvailable()(uint64,error){b,e:=os.ReadFile("/proc/meminfo");if e!=nil{return 0,e};for _,l:=range strings.Split(string(b),"\n"){f:=strings.Fields(l);if len(f)>=2&&f[0]=="MemAvailable:"{n,e:=strconv.ParseUint(f[1],10,64);return n*1024,e}};return 0,fmt.Errorf("MemAvailable unavailable")}
func snapshot(dir,name string)error{m:=map[string]any{"utc":time.Now().UTC().Format(time.RFC3339Nano),"go_version":runtime.Version(),"pid":os.Getpid(),"note":"/proc visibility does not guarantee visibility of any hidden cgroup or container limit; hard process cap is virtual memory, not RSS."};for _,p:=range []string{"/proc/meminfo","/proc/self/limits","/proc/self/status","/proc/self/cgroup","/sys/fs/cgroup/memory.max","/sys/fs/cgroup/memory.current","/sys/fs/cgroup/memory/memory.limit_in_bytes"}{b,e:=os.ReadFile(p);if e!=nil{m[p]=map[string]string{"unavailable":e.Error()}}else{m[p]=string(b)}};return writeNew(filepath.Join(dir,name),m)}
func admit(dir,dataset string)error{if e:=snapshot(dir,"resource-before.json");e!=nil{return e};avail,e:=memoryAvailable();if e!=nil{return e};st,e:=os.Stat(dataset);if e!=nil{return e};if st.Size()>128<<20||st.Size()<2{return fmt.Errorf("outside frozen input byte bound")};need:=uint64(st.Size())*14+512*MiB;cap:=uint64(4096)*MiB;if avail<need+uint64(2048)*MiB{return fmt.Errorf("memory admission denied: available=%d need=%d plus 2GiB reserve",avail,need)};var lim syscall.Rlimit;if e=syscall.Getrlimit(syscall.RLIMIT_AS,&lim);e!=nil{return e};if lim.Cur<cap{cap=lim.Cur};if cap<need+uint64(1024)*MiB{return fmt.Errorf("existing address-space limit insufficient")};lim.Cur=cap;lim.Max=cap;if e=syscall.Setrlimit(syscall.RLIMIT_AS,&lim);e!=nil{return e};runtime.GOMAXPROCS(1);debug.SetMemoryLimit(1536<<20);return writeNew(filepath.Join(dir,"admission.json"),map[string]any{"available_bytes":avail,"estimated_working_bytes":need,"admission_formula":"14*model_bytes + 512MiB; require additional 2GiB MemAvailable reserve and 1GiB virtual-runtime headroom","model_bytes":st.Size(),"process_virtual_memory_hard_bytes":cap,"go_memory_soft_bytes":1536<<20,"gomaxprocs":1,"hidden_cgroup_limit_verified":false})}
// Run is the campaign CLI only. Synthetic unit tests call Produce/Verify directly
// and use entirely temporary tiny datasets, never a broader campaign query set.
func Run(mode string)int{
 fs:=flag.NewFlagSet(mode,flag.ContinueOnError);root:=fs.String("root","","lane source root");recipePath:=fs.String("recipe","","frozen tune-only recipe");window:=fs.String("window","","one of exactly two frozen tune windows");attempt:=fs.String("attempt-dir","","new create-only per-model attempt directory");candidate:=fs.String("candidate","","producer candidate file (verifier only)");seconds:=fs.Int("seconds",180,"whole-operation cooperative seconds, max180");maxRows:=fs.Uint64("max-rows",4000000,"maximum raw rows, max4000000")
 if e:=fs.Parse(os.Args[1:]);e!=nil{return 2};if *root==""||*recipePath==""||*window==""||*attempt==""||*seconds<1||*seconds>180||*maxRows==0||*maxRows>4000000{fmt.Fprintln(os.Stderr,"missing/invalid frozen-scope CLI inputs");return 2};if mode!="produce"&&mode!="verify"{return 2}
 rp,re:=filepath.Abs(*recipePath);expected,ee:=filepath.Abs(filepath.Join(*root,"RECIPE.json"));if re!=nil||ee!=nil||rp!=expected{fmt.Fprintln(os.Stderr,"recipe must be frozen lane RECIPE.json");return 2}
 r,j,e:=LoadRecipe(*recipePath,*window);if e!=nil{fmt.Fprintln(os.Stderr,e);return 2};fr,e:=frozen(*root);if e!=nil{fmt.Fprintln(os.Stderr,e);return 2};pb,e:=os.ReadFile(filepath.Join(*root,"PROTOCOL.md"));if e!=nil||SHA(pb)!=r.ProtocolSHA{fmt.Fprintln(os.Stderr,"protocol mismatch");return 2};if e=os.Mkdir(*attempt,0755);e!=nil{fmt.Fprintln(os.Stderr,e);return 2}
 fail:=func(err error)int{_ = writeNew(filepath.Join(*attempt,"failure.json"),map[string]any{"kind":"invalid_or_inconclusive_no_certificate","error":err.Error(),"mode":mode,"window":*window,"original_scalar_slots_unchanged":true});_ = snapshot(*attempt,"resource-after.json");fmt.Fprintln(os.Stderr,err);return 1}
 lock,e:=os.OpenFile(globalLock,os.O_RDWR,0600);if e!=nil{return fail(e)};defer lock.Close();if e=syscall.Flock(int(lock.Fd()),syscall.LOCK_EX|syscall.LOCK_NB);e!=nil{return fail(fmt.Errorf("campaign CPU lock unavailable: %w",e))};defer syscall.Flock(int(lock.Fd()),syscall.LOCK_UN)
 if e=admit(*attempt,j.Dataset);e!=nil{return fail(e)};g:=&Guard{Deadline:time.Now().Add(time.Duration(*seconds)*time.Second),MaxRows:*maxRows};var out any
 if mode=="produce"{v,er:=Produce(j,*root,r.ProtocolSHA,fr,g);e=er;out=v}else{if *candidate==""{return fail(fmt.Errorf("candidate required"))};raw,er:=loadSmall(*candidate,16<<20);if er!=nil{return fail(er)};v,er:=Verify(j,*root,r.ProtocolSHA,fr,raw,g);e=er;out=v};if e!=nil{return fail(e)};if e=g.Check();e!=nil{return fail(e)};name:="candidate.json";if mode=="verify"{name="verified-certificate.json"};if e=writeNew(filepath.Join(*attempt,name),out);e!=nil{return fail(e)};if e=snapshot(*attempt,"resource-after.json");e!=nil{return fail(e)};b,_:=json.Marshal(map[string]any{"mode":mode,"window":*window,"output":filepath.Join(*attempt,name)});fmt.Println(string(b));return 0
}
