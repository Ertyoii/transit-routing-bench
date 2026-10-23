"""Small typed inventory adapter for the one shared canonical JSON resolver.

No monkeypatch, temporary raw file, model, scorer or new native completeness
method. inject unchanged inv, qualified native parity module and shared io.
This exposes the legacy method signatures, not an invented legacy result schema.
"""
from collections import Counter
from pathlib import Path


class InventoryProxy:
    def __init__(self,inv,io,native):
        self.inv,self.io,self.native=inv,io,native

    def __getattr__(self,name):
        return getattr(self.inv,name)

    def load_passes(self,summary,artifact,expected,driver,argv,algorithm,bindings):
        self.native.need(bindings is self.io.bindings,"inventory binding map is not shared canonical IO")
        chosen,controls,observed,sidecars,diagnostics=self.native.load_passes(
            summary,Path(artifact),expected,driver,argv,algorithm,self.io,self.inv)
        make=lambda pair:{"algorithm":pair[1]["algorithm"],"descriptor":pair[0],"records":pair[1]["records"]}
        return [make(chosen)],[make(pair) for pair in controls],diagnostics

    def inspect_run(self,campaign,spec,freeze,bindings):
        n,inv,io=self.native,self.inv,self.io
        n.need(bindings is io.bindings,"inventory binding map is not shared canonical IO")
        campaign=Path(campaign);run=campaign/spec["id"]
        out={"schema":"native216-shared-canonical-transport-inventory-v1","id":spec["id"],
            "campaign":str(campaign),"family":spec.get("family"),"variant_id":spec.get("variant_id"),
            "window":spec.get("window"),"analysis_binding_error":None,"observed_rows":[],
            "independent_feasibility":"not_performed_by_transport_inventory",
            "quality_acceptance":False,"publication_first_answer_acceptance":False,
            "preparation_diagnosis":None,"native_complete":0}
        try:
            command=io.read_path(str(run/"command.json"));result=io.read_path(str(run/"result.json"))
            argv,driver,role,inputs=inv.validate_envelope(spec,command,result,freeze,run,campaign)
            workload_path=inv.flag(argv,"-queries");workload_sha=inputs[workload_path]["sha256"]
            workload=io.read_path(workload_path,expected_sha=workload_sha)
            dataset_sha=inputs[inv.flag(argv,"-dataset")]["sha256"]
            n.need(workload.get("dataset_sha256")==dataset_sha,"consumed workload/model SHA differs")
            expected=inv.expected_items(workload,driver,argv);algorithm=inv.algorithm(argv,driver)
            out.update(driver=driver,algorithm=algorithm,offered=len(expected),
                dataset_sha256=dataset_sha,workload_sha256=workload_sha,
                binding_status="typed_command_source_binary_input_envelope_matches_freeze")
            artifact=run/"artifact"
            path=artifact/("manifest.json" if driver in {"profilebench","tadbench"} else "summary.json")
            summary=io.read_path(str(path))
            inv.validate_manifest(summary,command,role,driver,algorithm,dataset_sha,workload_sha)
            state=inv.preparation_state(summary,driver,algorithm)
            out.update(n.preparation(summary,driver))
            out.update(preparation_status=state,preparation_diagnosis=inv.preparation_diagnosis(summary,driver,state),
                native_manifest_status=n.take(summary,("success","phase","error","complete","algorithm")))
            def observe(value):
                row=value["row"]
                out["observed_rows"].append({**{k:v for k,v in value.items() if k!="row"},
                    "offered_locator":n.identity(row,driver),**n.take(row,n.FLAGS+("response_ns","core_ns"))})
            chosen,controls,observed,sidecars,diagnostics=n.load_passes(
                summary,artifact,expected,driver,argv,algorithm,io,inv,observe)
            statuses=[inv.row_status(row,driver) for row in chosen[1]["records"]]
            out.update(native_complete=sum(n.native_complete(row,driver) for row in chosen[1]["records"]),
                native_row_statuses=dict(Counter(statuses)),artifact_io=sidecars,diagnostic_passes=diagnostics,
                status=inv.classify_failure(summary,result,state,statuses),
                supervisor=n.take(result,("ok","returncode","termination","timed_out","process_wall_s",
                    "elapsed_wall_s","sampled_peak_process_group_rss_bytes","wait4_ru_maxrss_kib","user_cpu_s","system_cpu_s")),
                timing_contract="native driver whole-unit response/core; separate pass IO/preparation/audit; no invented publication")
        except n.ERRORS as error:
            out.update(analysis_binding_error=type(error).__name__+": "+str(error),
                       status="analysis_binding_or_transport_error_not_native_family_failure")
        return out,None
