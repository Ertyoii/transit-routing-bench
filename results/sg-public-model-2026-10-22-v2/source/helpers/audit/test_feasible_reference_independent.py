"""Independent negative assertions over the worker's invented envelope builder.
No city model or router. Execute only in an allocated quiet slot.
"""
import collections,copy,importlib.util,pathlib,tempfile,unittest
P=pathlib.Path('/workspace/shared/sg-coldstart/campaign-v2-20261021/analysis/test_feasible_reference_v1.py')
s=importlib.util.spec_from_file_location('reference_independent_fixture_builder',P);f=importlib.util.module_from_spec(s);s.loader.exec_module(f)
class IndependentReference(unittest.TestCase):
 def test_partial_donation_only_reference_never_serving_or_scalar(self):
  with tempfile.TemporaryDirectory()as td:
   z=f.Fixture(td);im,pool=z.import_pool();out=z.directory/'independent-result';out.mkdir();rep=im.finalize(out)
   self.assertEqual((rep['offered_serving_rows_added'],rep['completed_serving_rows_added'],rep['scalar_slots_added']),(0,0,0));self.assertEqual(len(pool[(z.dataset_sha,z.query['id'])]),1);self.assertEqual(len(im.inventory),2);self.assertFalse(z.row['complete'])
 def test_recipient_same_id_maxlegs_mismatch_not_a_join(self):
  with tempfile.TemporaryDirectory()as td:
   z=f.Fixture(td);im=z.importer();q=dict(z.query,max_legs=3)
   with self.assertRaises(ValueError):im.import_dataset(z.dataset_sha,z.checker,{(z.dataset_sha,q['id']):q},collections.defaultdict(dict),f.n.identity)
 def test_no_witness_false_missing_status_is_rejected(self):
  with tempfile.TemporaryDirectory()as td:
   z=f.Fixture(td);z.records=[];z.report['feasible_reference_witness_occurrences']=0;z.offer['native_row_present']=False;z.offer['status']='unavailable_native_row_or_binding';z.write_export()
   with self.assertRaises(ValueError):z.import_pool()
 def test_no_witness_native_complete_flip_cannot_be_laundered_via_report_count(self):
  with tempfile.TemporaryDirectory()as td:
   z=f.Fixture(td);z.records=[];z.report['feasible_reference_witness_occurrences']=0;z.offer['native_complete']=True;z.report['runs'][0]['native_complete_rows']=1;z.write_export()
   with self.assertRaises(ValueError):z.import_pool()
 def test_no_witness_query_cap_swap_even_consistent_local_fields_is_rejected(self):
  with tempfile.TemporaryDirectory()as td:
   z=f.Fixture(td);z.records=[];z.report['feasible_reference_witness_occurrences']=0;z.offer['query']=dict(z.query,max_legs=3);z.offer['offered_native_query']=copy.deepcopy(z.offer['query']);z.write_export()
   with self.assertRaises(ValueError):z.import_pool()
 def test_wrong_source_locator_cannot_be_replaced_by_equal_identity(self):
  with tempfile.TemporaryDirectory()as td:
   z=f.Fixture(td);z.records[0]['provenance']['native_record_index']=1;z.write_export()
   with self.assertRaises(ValueError):z.import_pool()
 def test_false_scalar_authority_even_with_feasible_journey_rejected(self):
  with tempfile.TemporaryDirectory()as td:
   z=f.Fixture(td);z.records[0]['scalar_optimality_claim']=True;z.write_export()
   with self.assertRaises(ValueError):z.import_pool()
 def test_full_reconstructed_pattern_and_duration_not_trusted(self):
  for name in ['duration_seconds','pattern']:
   with self.subTest(field=name),tempfile.TemporaryDirectory()as td:
    z=f.Fixture(td);z.records[0]['validated']=copy.deepcopy(z.checked);z.records[0]['validated'][name]=999 if name=='duration_seconds'else'fabricated';z.write_export()
    with self.assertRaises(ValueError):z.import_pool()
if __name__=='__main__':unittest.main(verbosity=2)
