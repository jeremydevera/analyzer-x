import pickle, numpy as np, time
import os; SP=os.environ.get("SCRATCH","./")  # folder for the intermediate files
P=pickle.load(open(SP+"v3pool.pkl","rb")); M=pickle.load(open(SP+"v3coinmeta.pkl","rb"))
cheap=lambda m:m and m['slip'] is not None and m['slip']<=0.0005 and m['kind']=='crypto'
rng=np.random.default_rng(7)
def get(ck):
    return np.concatenate([a for y in ("2025","2026") for w in ("older","unseen") for ci,a,_ in P[y]["R"].get((ck,w),[]) if cheap(M[y][ci])])
for ck in ("v3_trend|n20|4h|btc_mood","v3_trend|n20|4h|none","v3_trend|n50|1d|btc_mood","v3_trend|n20|1d|btc_mood"):
    a=get(ck); pnl=a[:,3]; wk=((a[:,0]//86400000)//7).astype(np.int64); wk-=wk.min()
    W=wk.max()+1; s=np.bincount(wk,weights=pnl,minlength=W); n=np.bincount(wk,minlength=W).astype(float)
    ms=[]
    for _ in range(4000):
        i=rng.integers(0,W,W); ms.append(s[i].sum()/n[i].sum())
    ms=np.array(ms)
    last=wk>=W-13  # last 13 weeks
    # halves in calendar time
    h=W//2
    print("%-28s %5d trades %+.3f$/tr | 90%% range (resampling whole weeks) %+.3f to %+.3f | share of resamples > 0: %.1f%% | first half %+.3f second half %+.3f | last 13 weeks %+.3f (%d trades)"%(
        ck,len(pnl),pnl.mean(),np.percentile(ms,5),np.percentile(ms,95),100*(ms>0).mean(),s[:h].sum()/n[:h].sum(),s[h:].sum()/n[h:].sum(),pnl[last].mean(),last.sum()))
