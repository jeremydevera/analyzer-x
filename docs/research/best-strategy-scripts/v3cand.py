import pickle, numpy as np, math, time
import os; SP=os.environ.get("SCRATCH","./")  # folder for the intermediate files
P=pickle.load(open(SP+"v3pool.pkl","rb")); M=pickle.load(open(SP+"v3coinmeta.pkl","rb"))
cheap=lambda m:m and m['slip'] is not None and m['slip']<=0.0005 and m['kind']=='crypto'
CAND=["v3_trend|n20|4h|none","v3_trend|n20|4h|btc_mood","v3_trend|n20|1d|none","v3_trend|n20|1d|btc_mood","v3_trend|n50|1d|none","v3_trend|n50|1d|btc_mood","v3_trend|n50|4h|btc_mood"]
def month(ms): 
    t=time.gmtime(ms/1000); return t.tm_year*12+t.tm_mon-1
def gather(ck):
    parts=[]
    for y in ("2025","2026"):
        for w in ("older","unseen"):
            for ci,a,why in P[y]["R"].get((ck,w),[]):
                if cheap(M[y][ci]): parts.append((y,w,ci,a))
    return parts
for ck in CAND:
    parts=gather(ck)
    a=np.concatenate([p[3] for p in parts])
    # entries sit in only one window; dedupe by (coin,entry) not needed (windows disjoint)
    pnl=a[:,3]; mo=np.array([month(x) for x in a[:,0]])
    ms=np.unique(mo)
    tot=np.array([pnl[mo==m].sum() for m in ms]); cnt=np.array([(mo==m).sum() for m in ms])
    green=(tot>0).sum()
    # cumulative by exit time for drawdown
    o=np.argsort(a[:,1]); cum=np.cumsum(pnl[o]); dd=(np.maximum.accumulate(cum)-cum).max()
    L=pnl[a[:,2]>0]; S=pnl[a[:,2]<0]
    w=pnl>0
    print("\n%s | trades %d, %d coins, months %d..%d"%(ck,len(pnl),len({(p[0],p[2]) for p in parts}),len(ms),0))
    print("  net %+.0f$ at $5 risk = %+.3f$/trade (%.1f%% of risk) ; win %.0f%% avg win %+.2f avg loss %.2f payoff %.2f"%(pnl.sum(),pnl.mean(),100*pnl.mean()/5,100*w.mean(),pnl[w].mean(),pnl[~w].mean(),-pnl[w].mean()/pnl[~w].mean()))
    print("  long n%d %+.3f | short n%d %+.3f"%(len(L),L.mean(),len(S),S.mean() if len(S) else float('nan')))
    print("  months green %d of %d ; worst month %+.0f, best %+.0f ; max drawdown %.0f$ ; monthly mean %+.0f sd %.0f -> Sharpe(month) %.2f"%(green,len(ms),tot.min(),tot.max(),dd,tot.mean(),tot.std(ddof=1),tot.mean()/tot.std(ddof=1)))
    # Kelly on the per-trade distribution (per $5 risk): fraction f maximizing mean log(1 + f*pnl/5)
    r=pnl/5.0
    best=max(((f,np.mean(np.log1p(np.clip(f*r,-0.999,None)))) for f in np.linspace(0.001,0.2,200)),key=lambda x:x[1])
    print("  Kelly on the trade distribution: risk %.1f%% of the account per trade (growth %.4f/trade); half-Kelly %.1f%%"%(100*best[0],best[1],50*best[0]))
    # random bar on unseen days
    for y in ("2025","2026"):
        if ck not in P[y]["RAND"]: continue
        cs=[c for c in P[y]["RAND"][ck] if cheap(M[y][c])]
        rr=np.sum([P[y]["RAND"][ck][c] for c in cs],axis=0)
        csset=set(cs); real=sum(p[1][:,3].sum() for p in P[y]["R"].get((ck,"unseen"),[]) if p[0] in csset)
        nreal=sum(len(p[1]) for p in P[y]["R"].get((ck,"unseen"),[]) if p[0] in csset)
        print("  %s unseen days: real %+.0f$ over %d trades vs 200 random-entry runs: mean %+.0f, best %+.0f -> real beats %d%% of them"%(y,real,nreal,rr.mean(),rr.max(),100*(rr<real).mean()))
