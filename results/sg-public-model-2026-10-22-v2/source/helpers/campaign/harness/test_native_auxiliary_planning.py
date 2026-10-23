"""Prepared unit guards only; not executed during the timing barrier.
No model, source-tree hash, binary, constructor or router is used.
"""
import copy
import unittest
from generate_native_auxiliary_plans import split_registry_runs

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

if __name__=='__main__':unittest.main()
