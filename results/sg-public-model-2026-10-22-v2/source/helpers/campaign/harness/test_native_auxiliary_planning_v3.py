"""Prepared unit guards only; not executed during the timing barrier.
No model, source-tree hash, binary, constructor or router is used.
"""
import copy
import unittest
from generate_native_auxiliary_plans_v3 import split_registry_runs,compact_trex_slots,TREX_FAMILIES

class NativeRegistryProjectionTests(unittest.TestCase):
 def test_two_registries_preserve_prepared_rows_and_inputs(self):
  prepared=[{'id':'primary0','registry':'primary','inputs':['p0']},
            {'id':'native0','registry':'native','inputs':['n0']},
            {'id':'primary1','registry':'primary','inputs':['p1']}]
  original=copy.deepcopy(prepared)
  primary=split_registry_runs(prepared,'primary',['freeze','coverage'])
  native=split_registry_runs(prepared,'native',['freeze','coverage'])
  self.assertEqual([x['id'] for x in primary],['primary0','primary1'])
  self.assertEqual([x['id'] for x in native],['native0'])
  self.assertEqual(prepared,original)
  self.assertTrue(all('registry' not in x for x in primary+native))
  self.assertEqual(primary[0]['inputs'],['p0','freeze','coverage'])
  primary[0]['inputs'].append('new-only')
  self.assertEqual(prepared,original)
 def test_repeated_projection_and_empty_registry_are_safe(self):
  prepared=[{'id':'n','registry':'native','inputs':[]}]
  first=split_registry_runs(prepared,'native',['x'])
  self.assertEqual(first,split_registry_runs(prepared,'native',['x']))
  self.assertEqual(split_registry_runs(prepared,'absent',['x']),[])
  self.assertEqual(prepared,[{'id':'n','registry':'native','inputs':[]}])

class CompactTREXSlotTests(unittest.TestCase):
 def fixtures(self):
  return [{'family':fam,'window':str(w),'driver':'familybench','source_role':'native_preparation_bounded_best','scoped_config':fam+('-bounded600-closure1m-transfers25m.json' if fam==TREX_FAMILIES[0] else '-fullmetric-closure9m-transfers25m.json'),'prep_timeout_s':900,'rss_stop_bytes':7000000000} for fam in TREX_FAMILIES for w in range(4)]
 def test_exactly_eight_equal_caps_and_original_unchanged(self):
  original=self.fixtures();before=copy.deepcopy(original);rows=compact_trex_slots(original,60)
  self.assertEqual(len(rows),8);self.assertEqual([x['order'] for x in rows],list(range(60,68)));self.assertEqual(original,before)
  for row,control in zip(rows,original):
   self.assertEqual(row['scoped_config'],control['scoped_config']);self.assertEqual(row['prep_timeout_s'],control['prep_timeout_s']);self.assertEqual(row['rss_stop_bytes'],control['rss_stop_bytes']);self.assertEqual(row['family'],control['family']);self.assertEqual(row['source_role'],'qualified_compact_trex')
 def test_missing_window_or_wrong_metric_is_rejected(self):
  with self.assertRaises(ValueError):compact_trex_slots(self.fixtures()[:-1],0)
  duplicate=self.fixtures();duplicate[0]['window']=duplicate[1]['window']
  with self.assertRaises(ValueError):compact_trex_slots(duplicate,0)
  rows=self.fixtures();rows[0]['scoped_config']='fixed-fullmetric.json'
  with self.assertRaises(ValueError):compact_trex_slots(rows,0)

if __name__=='__main__':unittest.main()
