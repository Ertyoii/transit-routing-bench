import osmium,json,time
start=time.time();result=[]
for r in osmium.FileProcessor('malaysia-singapore-brunei-261019.osm.pbf',entities=osmium.osm.RELATION):
 t=dict(r.tags)
 if t.get('public_transport') in {'stop_area','stop_area_group'} or t.get('boundary')=='administrative' and t.get('admin_level')=='2' and t.get('name')=='Singapore':
  result.append({'id':r.id,'tags':t,'members':[(m.type,m.ref,m.role) for m in r.members]})
open('transit-stop-areas.json','w').write(json.dumps(result,separators=(',',':'),sort_keys=True)+'\n')
print('transit relations',len(result),'seconds',time.time()-start)
