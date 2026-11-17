import numpy as np, json, time, math
import os; SP=os.environ.get("SCRATCH","./")  # folder for the intermediate files
d=np.load(SP+"v4trades.npz"); M=json.load(open(SP+"v4meta.json"))
ix=d["ix"];en=d["en"];pnl=d["pnl"].astype(np.float64);real=d["real"];gid=d["gid"];cost=d["cost"];tfi=d["tfi"];side=d["side"]
G=len(M["groups"]); tfs=["15m","30m","1h","4h","1d"]
# cost bucket per strategy
cb=np.where(cost<=0.25,0,np.where(cost<=0.5,1,2)).astype(np.int8)
tg=gid[ix]; tb=cb[ix]
cell=tg*3+tb
day=(en//86400).astype(np.int64); d0=day.min(); D=int(day.max()-d0+1)
day-=d0
SPLIT=int((1792195200//86400)-d0)  # Oct 17, 2026 (first whole day of real prices)
print("days",D,"split day idx",SPLIT)
tf_t=tfi[ix]
print("trades older/newer",(day<SPLIT).sum(),(day>=SPLIT).sum())
for t in range(5): print(tfs[t],"trades",(tf_t==t).sum(),"older",((tf_t==t)&(day<SPLIT)).sum(),"newer",((tf_t==t)&(day>=SPLIT)).sum(),"first",time.strftime('%b %d %Y',time.gmtime(en[tf_t==t].min())))
C=G*3
def agg(mask):
    n=np.bincount(cell[mask],minlength=C).astype(np.float64)
    s=np.bincount(cell[mask],weights=pnl[mask],minlength=C)
    # day-cluster: sums per cell-day
    key=cell[mask]*D+day[mask]
    sd=np.bincount(key,weights=pnl[mask],minlength=C*D).reshape(C,D)
    nd=np.bincount(key,minlength=C*D).reshape(C,D).astype(np.float64)
    m=np.divide(s,n,out=np.zeros(C),where=n>0)
    resid=sd-m[:,None]*nd
    se=np.sqrt((resid**2).sum(axis=1))/np.maximum(n,1)
    return n,m,se
allm=np.ones(len(pnl),bool)
n_o,m_o,se_o=agg(day<SPLIT)
n_n,m_n,se_n=agg(day>=SPLIT)
n_a,m_a,se_a=agg(allm)
meta=[]
for g,k in enumerate(M["groups"]):
    for b in range(3):
        c=g*3+b
        meta.append((c,k,b))
tstat=lambda m,se: np.where(se>0,m/se,0)
t_o=tstat(m_o,se_o);t_n=tstat(m_n,se_n);t_a=tstat(m_a,se_a)
# overall
print("ALL trades mean $/trade older %.3f newer %.3f"%(pnl[day<SPLIT].mean(),pnl[day>=SPLIT].mean()))
for b in range(3):
    mk=(tb==b)
    print(" cost bucket",["<=0.25","0.25-0.5",">0.5"][b],"trades",mk.sum(),"mean %.3f"%pnl[mk].mean(),"older %.3f newer %.3f"%(pnl[mk&(day<SPLIT)].mean(),pnl[mk&(day>=SPLIT)].mean()))
ok=(n_o>=300)&(n_n>=300)
print("cells with 300+ trades each side:",ok.sum(),"of",(n_a>0).sum())
print("older mean>0:",((m_o>0)&ok).sum()," newer mean>0:",((m_n>0)&ok).sum()," both>0:",((m_o>0)&(m_n>0)&ok).sum())
# THE forward test: choose on older (best t), judge on newer
idx=np.where(ok)[0]
top=idx[np.argsort(-t_o[idx])][:15]
print("\nchosen on older days (best t), result on newer:")
for c in top:
    g,b=divmod(c,3); k=M["groups"][g]
    print(f" {k[0]} {k[1]} {k[2]} tp{k[3]} sl{k[4]} cost{b} | older n{int(n_o[c])} {m_o[c]:+.3f} t{t_o[c]:.1f} | newer n{int(n_n[c])} {m_n[c]:+.3f} t{t_n[c]:.1f}")
# groups positive on newer with strong t
print("\nbest on newer days (for reference; selection on the test):")
top=idx[np.argsort(-t_n[idx])][:12]
for c in top:
    g,b=divmod(c,3); k=M["groups"][g]
    print(f" {k[0]} {k[1]} {k[2]} tp{k[3]} sl{k[4]} cost{b} | older n{int(n_o[c])} {m_o[c]:+.3f} t{t_o[c]:.1f} | newer n{int(n_n[c])} {m_n[c]:+.3f} t{t_n[c]:.1f}")
np.savez(SP+"pool.npz",n_o=n_o,m_o=m_o,se_o=se_o,n_n=n_n,m_n=m_n,se_n=se_n,n_a=n_a,m_a=m_a,se_a=se_a)
