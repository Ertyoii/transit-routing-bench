"""Focused synthetic value-equivalence test; no campaign payload access."""
import copy
import unittest

from compact_frontier_serialization_v1 import compact,identity


class SerializationEquivalence(unittest.TestCase):
    def test_complete_and_incomplete_difference_values_preserved(self):
        equal={'offered_locator':'q0','status':'complete_pair','exact':True,'objective':True,
               'incomplete_outcome_difference':None,'baseline_flags':{'complete':True},'candidate_flags':{'complete':True}}
        partial={'offered_locator':'q1','status':'incomplete_or_missing','exact':False,'objective':False,
                 'incomplete_outcome_difference':True,'baseline_flags':{'complete':False,'error':'cap'},
                 'candidate_flags':{'complete':False,'unsupported':True,'error':'semantic'}}
        changed={'offered_locator':'q2','status':'complete_pair','exact':False,'objective':True,
                 'baseline_flags':{'complete':True},'candidate_flags':{'complete':True}}
        for rows in ([equal],[equal,partial,changed]):
            with self.subTest(rows=len(rows)):
                pair={'baseline':'a','candidate':'b','status':'exact' if len(rows)==1 else 'unknown',
                    'rows':copy.deepcopy(rows),'p95_response_ratio':.9,'control_output_exact':True}
                contrast={'comparisons':[pair],'pooled_raw_response_p95_ratio_by_block':{'0':.9,'1':.92},
                    'native_exact_clock_gate':len(rows)==1,'passes_frozen_native_response_same_cost_gate':False,
                    'max_whole_process_sampled_rss_ratio':1.02,'median_selected_router_preparation_ratio':1.01}
                value={'original_parity':[pair],'runtime_contrasts':[contrast],
                    'frozen_range_source_contrasts':[contrast],'corech_identity_controls':[],
                    'runtime_cells':[{'retained':True,'runtime':{'GOGC':'50','GOMEMLIMIT':'4GiB'}}]}
                before=copy.deepcopy(value);refs=[{'path':'/tmp/fixture-projections','sha256':'a'*64,'bytes':1}]
                result=compact(value,refs)
                self.assertEqual(value,before)
                self.assertEqual(result['runtime_cells'],value['runtime_cells'])
                for key,item in contrast.items():
                    if key!='comparisons':self.assertEqual(result['runtime_contrasts'][0][key],item)
                check=result['runtime_contrasts'][0]['comparisons'][0]
                for key,item in pair.items():
                    if key!='rows':self.assertEqual(check[key],item)
                self.assertEqual(check['row_projection']['matching_complete_rows'],1)
                self.assertEqual(check['row_projection']['matching_rows_identity_sha256'],identity([equal]))
                self.assertEqual(check['row_projection']['nonexact_rows'],rows[1:])
                self.assertEqual(check['row_projection']['complete_detail_sources'],refs)


if __name__=='__main__':unittest.main()
