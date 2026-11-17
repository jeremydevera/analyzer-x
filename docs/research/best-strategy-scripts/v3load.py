import gzip, json, os, time, numpy as np, pickle
import os; SP=os.environ.get("SCRATCH","./")  # folder for the intermediate files
base=os.path.expanduser('~/.tradingagents/v3/research')
t0=time.time()
out={}
for year,folder in (("2026","all-coins"),("2025","all-2025")):
    files=sorted(f for f in os.listdir(os.path.join(base,folder)) if f.endswith('.json.gz'))
    combos=None
    R={}   # (combo,win) -> lists
    RAND={} # combo -> {coin: [totals]}
    coins=[]
    nfail=0
    for i,f in enumerate(files):
        try: r=json.load(gzip.open(os.path.join(base,folder,f)))
        except Exception as e: nfail+=1; continue
        if not r.get('combos'): continue
        coin=r['coin']; coins.append(coin); ci=len(coins)-1
        for ck,cv in r['combos'].items():
            for win in ('older','unseen'):
                rows=cv[win]['rows']
                if not rows: continue
                a=np.array([[x[1],x[2],x[3],x[4]] for x in rows],dtype=np.float64)  # entry_ms, exit_ms, side, pnl
                R.setdefault((ck,win),[]).append((ci,a, [x[5] for x in rows]))
            rl=cv.get('random')
            if rl: RAND.setdefault(ck,{})[ci]=np.array([x[1] for x in rl],dtype=np.float64)
        if i%200==0: print(year,i,len(files),round(time.time()-t0),"s",flush=True)
    out[year]=dict(coins=coins,R=R,RAND=RAND,nfail=nfail)
    print(year,"coins",len(coins),"combos",len({k[0] for k in R}),"failed",nfail,flush=True)
pickle.dump(out,open(SP+"v3pool.pkl","wb"),protocol=4)
print("saved",round(time.time()-t0),"s")
