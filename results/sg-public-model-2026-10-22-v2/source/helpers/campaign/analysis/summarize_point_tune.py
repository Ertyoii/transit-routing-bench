#!/usr/bin/env python3
"""Hash-bound descriptive tune summary. No selection or router execution.

Quantiles are pooled from actual ordinary response rows, never averaged p95s.
Source-only gates preserve every block/window and explicit resource regressions.
"""
import argparse, collections, hashlib, json, math, statistics
from pathlib import Path


def read(path): return json.loads(Path(path).read_text())
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def distribution(xs):
    xs=sorted(xs); n=len(xs)
    return {"count":n, **{key: xs[math.ceil(n*p)-1] if n else None for key,p in [("p50",.5),("p95",.95),("p99",.99)]}, "max":xs[-1] if n else None}


def summarize(campaign, evaluation, parity, out):
    campaign=Path(campaign).resolve(); evaluation=Path(evaluation).resolve()
    inputs={str(Path(__file__).resolve()):sha(__file__)}
    def bound(path):
        path=Path(path); inputs[str(path.resolve())]=sha(path); return read(path)
    plan=bound(campaign/"plan.json"); report=bound(evaluation/"REPORT.json")
    metrics=bound(evaluation/"METRICS_BY_RUN.json")
    quality=bound(evaluation/"QUALITY_AGGREGATE.json")
    scalar=bound(evaluation/"ORACLE_COMPARISONS.json")
    parity_report=bound(parity)
    runs={run["id"]:run for run in plan["runs"]}
    by_variant=collections.defaultdict(list); response=collections.defaultdict(list)
    quality_ns=collections.defaultdict(list); offered_keys=set()
    for metric in metrics:
        run=runs[metric["id"]]; variant=metric["variant_id"]; block=run["block"]
        by_variant[variant].append(metric)
        artifact=campaign/run["id"]/"artifact"; summary=read(artifact/"summary.json")
        if sha(artifact/"summary.json")!=report["inputs"].get(str(artifact/"summary.json")): raise ValueError("summary no longer bound")
        for desc in summary.get("passes",[]):
            if desc.get("forced") or desc.get("warmup"): continue
            path=artifact/desc["file"]
            if sha(path)!=desc["sha256"] or sha(path)!=report["inputs"].get(str(path)): raise ValueError("pass no longer bound")
            for row in read(path)["records"]:
                offered_keys.add((metric["dataset_sha256"],row["query"]["id"]))
                if row["attempted"]:
                    response[(variant,block)].append(row["response_ns"])
                    quality_ns[(variant,block)].append(row["quality_ns"])
    thresholds=collections.defaultdict(collections.Counter)
    quality_rows=evaluation/"QUALITY_ROWS.jsonl";inputs[str(quality_rows)]=sha(quality_rows)
    with quality_rows.open() as stream:
        for line in stream:
            row=json.loads(line)
            for panel,key in [("full","score"),("leave_family_out","leave_donor_family_out_signed")]:
                value=row[key];counter=thresholds[(row["variant_id"],row["stage"],panel)]
                for field in ["within30","within60","within120","within1percent","within5percent"]:counter[field]+=value.get(field,0)
    variants={}
    for variant, rows in sorted(by_variant.items()):
        stages={}
        for stage in ["raw","final","display"]:
            stages[stage]={}
            for panel in ["full","leave_family_out"]:
                cells=[x for x in quality if x["variant_id"]==variant and x["stage"]==stage and x["panel"]==panel]
                eligible=sum(x["eligible"] for x in cells); covered=sum(x["covered"] for x in cells)
                stages[stage][panel]={"eligible_repeated_preference_slots":eligible,"covered":covered,"exact_coverage":covered/eligible if eligible else None,"missing":sum(x["missing"] for x in cells),"worst_signed_score_seconds":max((x["regret_score_seconds"]["max"] for x in cells if x["regret_score_seconds"]["max"] is not None),default=None),"worst_signed_normalized_regret":max((x["normalized_regret"]["max"] for x in cells if x["normalized_regret"]["max"] is not None),default=None),**thresholds[(variant,stage,panel)]}
        scalar_stages={}
        for stage in ["raw","final","display"]:
            cells=[x for x in scalar if x["variant_id"]==variant and x["stage"]==stage]
            found=[x for x in cells if x["reference_complete"] and x["reference_found"]]
            scored=[x for x in found if "signed_regret" in x]
            scalar_stages[stage]={"offered_repeated_slots":len(cells),"reference_complete_found":len(found),"reference_complete_empty":sum(x["reference_complete"] and not x["reference_found"] for x in cells),"reference_unknown":sum(not x["reference_complete"] for x in cells),"scored_found":len(scored),"exact_found":sum(x["signed_regret"]<=1e-7*max(1,abs(x["reference_optimum"])) for x in scored),"worst_regret_score_seconds":max((x["signed_regret"] for x in scored),default=None)}
        variants[variant]={"offered_repeated_queries":sum(x["offered"] for x in rows),"independently_complete":sum(x["completed"] for x in rows),"quality":stages,"scalar9":scalar_stages,"pooled_response_ns_by_block":{str(block):distribution(response[(variant,block)]) for block in sorted({runs[x["id"]]["block"] for x in rows})},"pooled_quality_ns_by_block":{str(block):distribution(quality_ns[(variant,block)]) for block in sorted({runs[x["id"]]["block"] for x in rows})},"median_preparation_ns":statistics.median(x["preparation"]["elapsed_ns"] for x in rows),"median_quality_preparation_ns":statistics.median(x["quality_preparation"]["elapsed_ns"] for x in rows),"max_sampled_process_group_rss_bytes":max(x["sampled_peak_rss_bytes"] for x in rows),"median_accepted_native_launch_ns":statistics.median(x["accepted_native_launch_to_first_available_answer_ns"] for x in rows if x["accepted_native_launch_to_first_available_answer_ns"] is not None),"per_run":rows}
    source_comparisons=[]
    for group in parity_report["source_groups"]:
        baseline=group[0]
        for candidate in group[1:]:
            if baseline not in variants or candidate not in variants: continue
            a,b=variants[baseline],variants[candidate]
            block_ratios={block:b["pooled_response_ns_by_block"][block]["p95"]/a["pooled_response_ns_by_block"][block]["p95"] for block in a["pooled_response_ns_by_block"]}
            left={(runs[x["id"]]["block"],x["window"]):x for x in a["per_run"]}
            windows=[{"block":runs[x["id"]]["block"],"window":x["window"],"p95_ratio":x["all_attempted_response_ns"]["p95"]/left[(runs[x["id"]]["block"],x["window"])]["all_attempted_response_ns"]["p95"]} for x in b["per_run"]]
            rss=b["max_sampled_process_group_rss_bytes"]/a["max_sampled_process_group_rss_bytes"]
            prep=b["median_preparation_ns"]/a["median_preparation_ns"]
            checks=[x for x in parity_report["checks"] if runs[x["baseline"]]["variant_id"]==baseline and runs[x["candidate"]]["variant_id"]==candidate]
            exact=bool(checks) and all(x["status"]=="exact" for x in checks)
            gate=exact and all(ratio<=.97 for ratio in block_ratios.values()) and all(x["p95_ratio"]<=1.03 for x in windows) and rss<=1.05 and prep<=1.05
            source_comparisons.append({"baseline":baseline,"candidate":candidate,"ordered_native_output_parity":exact,"pooled_p95_ratio_by_block":block_ratios,"per_window_block_p95_ratios":windows,"max_sampled_rss_ratio":rss,"median_preparation_ratio":prep,"passes_preregistered_same_cost_speedup_gate":gate,"scope":"Tune descriptive evidence only; not final validation plateau or production-tail superiority."})
    # Raw preparation objects can retain large native diagnostic snapshots.
    # Keep them in their original hash-bound artifacts, not duplicated here.
    for variant in variants.values():
        variant['per_run']=[{key:row[key] for key in ['id','window','offered','completed','statuses','all_attempted_response_ns','accepted_native_launch_to_first_available_answer_ns','first_published_native_row_accepted','first_marker_matches_first_offered_query','sampled_peak_rss_bytes']} for row in variant['per_run']]
    value={"schema":"sg-v2-point-tune-frontier-summary-v1","inputs":inputs,"offered_repeated_queries":sum(x["offered"] for x in metrics),"independently_complete":sum(x["completed"] for x in metrics),"unique_tune_requests":len(offered_keys),"unique_request_count_scope":"exact dataset/query identity set from bound ordinary pass rows; repeated variants and blocks do not add demand","independent_reconstruction_errors":report["independent_reconstruction_errors"],"native_contract_counterexamples":report["native_contract_counterexamples"],"original_oracle_offered_slots":report["oracle_offered_slots"],"original_oracle_complete_slots":report["oracle_complete_slots"],"variants":variants,"source_comparisons":source_comparisons,"limitations":["All preference-union/LOFO quality is incomplete-pool diagnostic, not global truth.","Scalar9 proves only complete exact weighted slots; unknown references remain offered.","No source/runtime/selector winner is promoted before validation/replay and independent receipt review.","Same-cost gate requires >=3% pooled p95 improvement in both blocks, no >3% window regression, <=5% RSS and median-preparation regression.","Quantiles are empirical nearest rank on actual repeated offers, not independent passenger demand or production tails."]}
    with Path(out).open("x") as stream:json.dump(value,stream,sort_keys=True,indent=2);stream.write("\n")
    print(json.dumps({"offered":value["offered_repeated_queries"],"complete":value["independently_complete"],"source_same_cost_gate_passes":[x["candidate"] for x in source_comparisons if x["passes_preregistered_same_cost_speedup_gate"]]}))


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--campaign",required=True);parser.add_argument("--evaluation",required=True);parser.add_argument("--parity",required=True);parser.add_argument("--out",required=True);args=parser.parse_args();summarize(args.campaign,args.evaluation,args.parity,args.out)
