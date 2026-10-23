"""Independent invented native profile/donation negatives. No city model/router.
Run only in an owner-allocated quiet slot; production helper path is explicit.
"""
import copy,importlib.util,pathlib,unittest
P=pathlib.Path('/workspace/shared/sg-coldstart/campaign-v2-20261021/analysis/audit_native_transit_v1.py')
s=importlib.util.spec_from_file_location('native_transit_independent_target',P);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

def fixture():
 d={'schema_version':'0.2','id':'independent-profile','time_zone':'UTC','service_date':'2026-10-20',
  'stops':[{'id':x,'accessible':'yes'}for x in ['A','B','C']],
  'trips':[{'id':'T','accessible':'yes'}],
  'connections':[{'id':'BC','trip_id':'T','from':'B','to':'C','departure':20,'arrival':25,'sequence':0,'pickup':True,'dropoff':True}],
  'footpaths':[{'id':'AB','from':'A','to':'B','duration':5,'accessible':'yes'},{'id':'AC','from':'A','to':'C','duration':30,'accessible':'yes'}]}
 q={'id':'independent-q','origin':'A','destination':'C','departure':10,'latest_arrival':50,'transfer_buffer':0,'max_walk_seconds':100,'max_boardings':1,'max_legs':10,'accessible_only':False,'walking_limits':{'access_seconds':5,'transfer_seconds':5,'egress_seconds':5,'direct_seconds':30}}
 c=m.legacy.Checker(d);profile={'base':q,'ready_window_end_inclusive':20}
 j={'legs':[{'kind':'walk','ref':'AB','departure':15,'arrival':20},{'kind':'ride','ref':'BC','departure':20,'arrival':25}]}
 v=c.check(m.point_query(q,15),j)
 raw={'latest_ready':15,'arrival':25,'boardings':1,'journey':j};final={'latest_ready':15,'validated':v}
 row={'query':copy.deepcopy(profile),'raw':{'query':copy.deepcopy(profile),'transit_points':[raw],'complete':True},'final_points':[final],'complete':True}
 row['every_integer_ready_time']=m.materializations(c,profile,[raw],None)[0]
 return c,profile,row

class NativeIndependent(unittest.TestCase):
 def test_original_ready_donation_has_original_duration(self):
  c,p,r=fixture();ds,fs=m.base_donations(c,r,'profilebench');self.assertEqual(fs,[])
  v,prov=ds['final'][0];self.assertEqual(v['duration_seconds'],15);self.assertEqual(v['journey']['legs'][0]['departure'],10);self.assertEqual(v['journey']['legs'][1],r['raw']['transit_points'][0]['journey']['legs'][1]);self.assertEqual(prov['source_ready'],15)
 def test_late_start_claim_not_directly_accepted_under_base(self):
  c,p,r=fixture()
  with self.assertRaises(ValueError):c.check(p['base'],r['final_points'][0]['validated'])
 def test_source_partial_error_never_blocks_feasible_reference(self):
  c,p,r=fixture();r['complete']=False;r['raw']['complete']=False;r['error']='guard';ds,fs=m.base_donations(c,r,'profilebench');self.assertEqual(len(ds['raw']),1);self.assertEqual(len(ds['final']),1);self.assertEqual(fs,[]);self.assertFalse(r['complete'])
 def test_malformed_sibling_preserves_valid_occurrences(self):
  c,p,r=fixture();r['raw']['transit_points'].append({'latest_ready':15});ds,fs=m.base_donations(c,r,'profilebench');self.assertEqual(len(ds['raw']),1);self.assertEqual(len(ds['final']),1);self.assertEqual(len(fs),1)
 def test_non_object_sibling_preserves_valid_occurrences(self):
  c,p,r=fixture();r['raw']['transit_points'].insert(0,None);ds,fs=m.base_donations(c,r,'profilebench');self.assertEqual(len(ds['raw']),1);self.assertEqual(len(ds['final']),1);self.assertEqual(len(fs),1);self.assertEqual(ds['raw'][0][1]['source_point_index'],1)
 def test_bool_boarding_metadata_is_rejected(self):
  c,p,r=fixture();r['raw']['transit_points'][0]['boardings']=True
  with self.assertRaises(ValueError):m.audit_profile(c,r)
 def test_conservative_boundary_extension_falsifies_only_claimed_grid(self):
  c,p,r=fixture();j=m.independent_reanchor(c,r['raw']['transit_points'][0]['journey'],14);r['raw']['transit_points'][0].update(latest_ready=14,journey=j);r['final_points'][0]={'latest_ready':14,'validated':c.check(m.point_query(p['base'],14),j)};r['every_integer_ready_time']=m.materializations(c,p,r['raw']['transit_points'],None)[0]
  a=m.audit_profile(c,r);self.assertEqual(a['conservative_point_boundary_count'],1);self.assertEqual([(x['ready'],x['boarding_cap'])for x in a['physical_extension_counterexamples']],[(15,1)])
 def test_recipient_hard_cap_rechecked_on_donation(self):
  c,p,r=fixture();r['query']['base']['max_boardings']=0;r['raw']['query']=copy.deepcopy(r['query']);ds,fs=m.base_donations(c,r,'profilebench');self.assertEqual(ds,{'raw':[],'final':[]});self.assertEqual(len(fs),2)
 def test_identity_source_corruption_can_donate_only_as_rechecked_raw(self):
  c,p,r=fixture();r['final_points'][0]['validated']['identity']='not-a-source-identity';ds,fs=m.base_donations(c,r,'profilebench');self.assertEqual(fs,[]);v,pr=ds['final'][0];self.assertFalse(pr['source_feasible_at_emitted_ready']);self.assertIsNotNone(pr['source_ready_validation_error']);self.assertNotEqual(v['identity'],'not-a-source-identity')

if __name__=='__main__':unittest.main(verbosity=2)
