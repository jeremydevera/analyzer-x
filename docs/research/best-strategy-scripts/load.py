import sqlite3, os, time, numpy as np, json
t0=time.time()
import os; SP=os.environ.get("SCRATCH","./")  # folder for the intermediate files
p=os.path.expanduser('~/.tradingagents/v4/rows.db')
c=sqlite3.connect('file:'+p+'?mode=ro',uri=True)
S=c.execute("select sid,coin,tf,strategy,params,tp,sl,fee,slip,skill from strat where coin not in ('TWUMC','WUXIBIO')").fetchall()
print(len(S),"strategies")
sid=np.array([s[0] for s in S]); 
order={s[0]:i for i,s in enumerate(S)}
# groups
gkey={}
gid=np.zeros(len(S),np.int32)
cost=np.zeros(len(S),np.float32)
tfs=["15m","30m","1h","4h","1d"]
tfi=np.zeros(len(S),np.int8)
for i,s in enumerate(S):
    k=(s[2],s[3],s[4],s[5],s[6])
    gid[i]=gkey.setdefault(k,len(gkey))
    cost[i]=100*(2*s[7]+2*s[8])
    tfi[i]=tfs.index(s[2])
print("groups",len(gkey),"cost$ median",np.median(cost))
# trades
n=c.execute("select count(*) from trade").fetchone()[0]
print("trades",n)
sidmap=np.full(max(sid)+1,-1,np.int32); sidmap[sid]=np.arange(len(S))
A_s=np.empty(n,np.int32);A_en=np.empty(n,np.int64);A_ex=np.empty(n,np.int64);A_pnl=np.empty(n,np.float32);A_real=np.empty(n,np.int8);A_side=np.empty(n,np.int8);A_why=np.empty(n,np.int8)
i=0
cur=c.execute("select sid,en,ex,pnl,real,side,why from trade")
while True:
    rows=cur.fetchmany(500000)
    if not rows: break
    m=len(rows)
    a=np.array(rows,dtype=np.float64)
    A_s[i:i+m]=a[:,0];A_en[i:i+m]=a[:,1];A_ex[i:i+m]=a[:,2];A_pnl[i:i+m]=a[:,3];A_real[i:i+m]=a[:,4];A_side[i:i+m]=a[:,5];A_why[i:i+m]=a[:,6]
    i+=m
print("loaded",i,round(time.time()-t0),"s")
ix=sidmap[A_s]; keep=ix>=0
np.savez(SP+"v4trades.npz",ix=ix[keep],en=A_en[keep],ex=A_ex[keep],pnl=A_pnl[keep],real=A_real[keep],side=A_side[keep],why=A_why[keep],
         gid=gid,cost=cost,tfi=tfi)
json.dump({"groups":[list(k) for k,_ in sorted(gkey.items(),key=lambda x:x[1])],"coins":[s[1] for s in S],"strategies":[s[3] for s in S],"sid":[int(s[0]) for s in S]},open(SP+"v4meta.json","w"))
print("saved",int(keep.sum()),round(time.time()-t0),"s")
print("why values",np.unique(A_why,return_counts=True),"side",np.unique(A_side,return_counts=True))
print("en range",time.ctime(A_en.min()),time.ctime(A_en.max()))
