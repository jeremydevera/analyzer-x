import gzip, json, os, pickle, numpy as np
import os; SP=os.environ.get("SCRATCH","./")  # folder for the intermediate files
base=os.path.expanduser('~/.tradingagents/v3/research')
P=pickle.load(open(SP+"v3pool.pkl","rb"))
meta={}
for year,folder in (("2026","all-coins"),("2025","all-2025")):
    files=sorted(f for f in os.listdir(os.path.join(base,folder)) if f.endswith('.json.gz'))
    names=P[year]["coins"]; pos={n:i for i,n in enumerate(names)}
    m=[None]*len(names)
    for f in files:
        try: r=json.load(gzip.open(os.path.join(base,folder,f)))
        except Exception: continue
        if not r.get('combos'): continue
        i=pos.get(r['coin'])
        if i is None: continue
        pre=r['pre']
        m[i]=dict(coin=r['coin'],kind=r.get('kind'),slip=pre.get('flat_slip'),slip_older=pre.get('flat_slip_older'),cov_older=pre.get('coverage_older'),cov_unseen=pre.get('coverage_unseen'),
                  maxlev=pre['contract'].get('max_lev'),cycle=pre.get('cycle_h'))
    meta[year]=m
pickle.dump(meta,open(SP+"v3coinmeta.pkl","wb"))
for y in meta:
    s=np.array([x['slip'] for x in meta[y] if x and x['slip'] is not None])
    print(y,"coins",len(s),"flat_slip percentiles 10/25/50/75/90:",np.percentile(s,[10,25,50,75,90]).round(5))
    k={}
    for x in meta[y]:
        if x: k[x['kind']]=k.get(x['kind'],0)+1
    print(y,k)
