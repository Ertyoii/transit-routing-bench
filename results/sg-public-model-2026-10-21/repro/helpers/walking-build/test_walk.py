import unittest,build_walk as w
class PolicyTests(unittest.TestCase):
 def test_explicit_denials(self):
  for tag in [{'foot':'no'},{'access':'private'},{'foot':'use_sidepath'},{'foot':'customers'},{'foot:conditional':'yes @ (Mo-Fr)'}]:
   self.assertFalse(any(w.policy(dict(highway='footway',**tag))[:2]),tag)
 def test_override(self):self.assertEqual(w.policy({'highway':'footway','access':'private','foot':'yes'})[:2],(True,True))
 def test_directions(self):
  self.assertEqual(w.policy({'highway':'footway','oneway:foot':'yes'})[:2],(True,False))
  self.assertEqual(w.policy({'highway':'footway','oneway:foot':'-1'})[:2],(False,True))
  self.assertEqual(w.policy({'highway':'residential','oneway':'yes','foot':'yes'})[:2],(True,True))
  self.assertEqual(w.policy({'highway':'footway','oneway':'yes'})[:2],(False,False))
 def test_no_roads_by_default(self):
  for h in ['motorway','trunk','primary','secondary','tertiary','residential','service','cycleway']:
   self.assertEqual(w.policy({'highway':h})[:2],(False,False),h)
 def test_no_dynamic(self):
  for ts in [{'highway':'steps','conveying':'forward'},{'highway':'elevator'},{'highway':'footway','opening_hours':'Mo-Fr 9:00-18:00'},{'highway':'footway','construction':'yes'},{'highway':'footway','area':'yes'},{'highway':'footway','ford':'yes'}]:self.assertFalse(any(w.policy(ts)[:2]),ts)
 def test_node_barriers(self):
  for ts in [{'barrier':'fence'},{'barrier':'gate'},{'barrier':'wall','foot':'no'},{'barrier':'gate','foot':'yes','locked':'yes'}]:self.assertFalse(w.node_allowed(ts))
  self.assertTrue(w.node_allowed({'barrier':'gate','foot':'yes'}))
 def test_cost(self):
  self.assertEqual(w.cost(0),1);self.assertEqual(w.cost(1.4),1);self.assertEqual(w.cost(1.40001),2)
 def test_distance(self):self.assertAlmostEqual(w.dist((1.3,103.8),(1.301,103.8)),111.19508,places=4)
if __name__=='__main__':unittest.main()
