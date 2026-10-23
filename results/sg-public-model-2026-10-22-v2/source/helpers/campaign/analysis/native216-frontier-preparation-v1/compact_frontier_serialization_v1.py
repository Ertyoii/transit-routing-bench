"""Operational output compaction only. No scoring, native witness or gate math.

Matching-row detail remains in the referenced complete projection/parity inputs.
Every nonmatching, missing, incomplete or status-difference row stays verbatim.
Every non-row field, dictionary, ratio and gate result is copied unchanged.
"""
import hashlib
import json


def identity(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def matching(row):
    if 'status' in row:
        return (row.get('status')=='complete_pair' and row.get('exact') is True
                and row.get('objective') is True and row.get('incomplete_outcome_difference') in (None,False))
    return (row.get('complete_pair') is True and row.get('native_objective_equal') is True
            and row.get('full_witness_output_equal') is True)


def pair(value,source_refs):
    if not isinstance(value,dict) or not isinstance(value.get('rows'),list):return value
    rows=value['rows'];equal=[row for row in rows if matching(row)]
    result={key:item for key,item in value.items() if key!='rows'}
    result['row_projection']={'offered_rows':len(rows),'matching_complete_rows':len(equal),
        'matching_rows_identity_sha256':identity(equal),
        'nonexact_rows':[row for row in rows if not matching(row)],
        'complete_detail_sources':source_refs,
        'run_refs':{key:value[key] for key in ('id','baseline','candidate') if key in value},
        'scope':'Matching detail referenced, never discarded or treated as missing; all nonexact rows verbatim.'}
    return result


def compact(frontier,source_refs):
    out=dict(frontier)
    out['original_parity']=[pair(value,source_refs) for value in frontier['original_parity']]
    for field in ('runtime_contrasts','frozen_range_source_contrasts'):
        out[field]=[{**value,'comparisons':[pair(check,source_refs) for check in value['comparisons']]}
                    for value in frontier[field]]
    out['corech_identity_controls']=[pair(value,source_refs) for value in frontier['corech_identity_controls']]
    out['serialization']={'schema':'native216-row-reference-serialization-v1',
        'source_refs':source_refs,'all_nonrow_fields_and_gate_math_unchanged':True,
        'nonexact_partial_or_status_difference_rows_retained_verbatim':True}
    return out
