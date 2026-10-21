import os
import subprocess
from pathlib import Path
R=Path(os.environ['SG_ROOT']);O=R/'public-campaign-20261021'
A=['raptor','raptor_early','ea_csa_layered','ultra_transfer_complete_capped','ultra_cap_safe_stay_witness_subset_v1','mc_raptor','mc_raptor_early']
for w in ['midday','evening','overnight']:
 q=O/'bound-conservative600-v2'/f'weekday-{w}-20261020.screen.tune.primary_1h_walk600'
 cmd=['python3',str(R/'evalkit/evalkit.py'),'--dataset',str(R/'data-enriched/conservative600'/f'weekday-{w}-20261020/dataset.json'),'--queries',str(q)+'.json','--query-metadata',str(q)+'.metadata.json','--input-manifest',str(R/'data-enriched/NORMALIZED_INPUTS.json')]
 for a in A:cmd+=['--run',str(O/'screen-tune'/f'{w}-{a}'/'artifact')]
 cmd+=['--out',str(O/f'evalkit-screen-{w}-baseline')]
 subprocess.run(cmd,check=True)
