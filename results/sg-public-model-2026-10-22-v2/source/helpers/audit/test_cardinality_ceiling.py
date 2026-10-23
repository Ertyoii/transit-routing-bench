"""Original fixtures: exact brute-force comparison and guarded unknown contracts."""
import itertools,random,unittest
from diagnose_cardinality_ceiling import maximum_cover
class Ceiling(unittest.TestCase):
 def test_route_and_cardinality_gap_are_distinct(self):
  r=maximum_cover([0b000011,0b001100,0b010000],2);self.assertTrue(r['complete']);self.assertEqual(r['covered_lower_bound'],4);self.assertEqual(r['all_native_candidates_covered'],5)
 def test_dominance_duplicate_zero_masks_safe_for_unconstrained_score_coverage(self):
  r=maximum_cover([0,1,3,3,4],2);self.assertEqual(r['covered_lower_bound'],3);self.assertTrue(r['complete'])
 def test_guard_never_promotes_partial_result(self):
  r=maximum_cover([3,12,48],2,0);self.assertFalse(r['complete']);self.assertEqual(r['unknown_reason'],'max_work');self.assertEqual(r['covered_upper_bound'],6)
 def test_empty_native_pool_is_exact_zero_not_perfect_coverage(self):
  r=maximum_cover([],3);self.assertTrue(r['complete']);self.assertEqual(r['covered_lower_bound'],0)
 def test_random_exhaustive(self):
  rng=random.Random(20261021)
  for _ in range(150):
   masks=[rng.randrange(1<<12)for i in range(rng.randrange(1,10))]
   for k in [1,2,3,5]:
    want=max((__import__('functools').reduce(int.__or__,ss,0).bit_count()for size in range(min(k,len(masks))+1)for ss in itertools.combinations(masks,size)),default=0);r=maximum_cover(masks,k);self.assertTrue(r['complete']);self.assertEqual(r['covered_lower_bound'],want)

class InputContracts(unittest.TestCase):
 def fixture(self,reference,variants,max_vectors=1024):
  import tempfile,pathlib,json
  from diagnose_cardinality_ceiling import diagnose
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);root=pathlib.Path(tmp.name);p=root/'pools.jsonl';w=root/'weights.json';p.write_text(json.dumps({'dataset_sha256':'h','query_id':'q','common_reference':reference,'runs':variants})+'\n');w.write_text(json.dumps([{'transfer_seconds':0,'extra_walk_weight':0}]));return diagnose(p,w,root/'out.json',max_vectors=max_vectors)
 def f(self,d):return {'identity':str(d),'duration_seconds':d,'transfers':0,'walking_seconds':0}
 def test_empty_reference_unknown_row_retained(self):
  r=self.fixture([],[{'id':'run','variant_id':'v','complete':False,'native_final':[],'display':[]}]);self.assertEqual(r['offered_unique_queries'],1);self.assertEqual(r['rows'][0]['unknown_reason'],'reference_empty_or_unknown')
 def test_reference_guard_is_unknown_not_zero_display(self):
  r=self.fixture([self.f(1),self.f(2)],[{'id':'run','variant_id':'v','complete':True,'native_final':[self.f(1)],'display':[self.f(1)]}],1);self.assertEqual(r['rows'][0]['unknown_reason'],'max_reference_vectors');self.assertIsNone(r['rows'][0]['actual_display_covered'])
 def test_display_cannot_import_oracle_witness(self):
  with self.assertRaises(ValueError):self.fixture([self.f(1)],[{'id':'run','variant_id':'v','complete':True,'native_final':[self.f(2)],'display':[self.f(1)]}])
 def test_candidate_beating_common_reference_is_not_clipped(self):
  with self.assertRaises(ValueError):self.fixture([self.f(2)],[{'id':'run','variant_id':'v','complete':True,'native_final':[self.f(1)],'display':[self.f(1)]}])

if __name__=='__main__':unittest.main(verbosity=2)
