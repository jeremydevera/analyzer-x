"""Standalone HTML grid for a backtest sweep.

Rendered by :mod:`tradingagents.backtest_report`. Carries CLAUDE.md's
standard kit: stable row IDs, per-row trade logs replayed from embedded
candles, a base-margin box that RE-SIMULATES, filters whose units match
their columns, month-by-month profit on every row, and the worst losing
streak beside the worst single trade.
"""

TEMPLATE = r"""<title>__TITLE__</title>
<style>
:root{--bg:#f7f6f3;--panel:#fff;--panel2:#f0eeea;--rule:#e0dcd4;--rule2:#c9c3b8;
 --ink:#1c1a17;--dim:#6b6459;--faint:#9a9287;--amber:#a86a12;--up:#137a45;--dn:#c0392b;--sel:#fdf4e3}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
 --bg:#07090b;--panel:#0d1115;--panel2:#121820;--rule:#1b232b;--rule2:#2c3844;
 --ink:#d3dbe3;--dim:#63717f;--faint:#3d4854;--amber:#f0a848;--up:#35d07f;--dn:#ff5f56;--sel:#161f14}}
:root[data-theme="dark"]{--bg:#07090b;--panel:#0d1115;--panel2:#121820;--rule:#1b232b;--rule2:#2c3844;
 --ink:#d3dbe3;--dim:#63717f;--faint:#3d4854;--amber:#f0a848;--up:#35d07f;--dn:#ff5f56;--sel:#161f14}
:root[data-theme="light"]{--bg:#f7f6f3;--panel:#fff;--panel2:#f0eeea;--rule:#e0dcd4;--rule2:#c9c3b8;
 --ink:#1c1a17;--dim:#6b6459;--faint:#9a9287;--amber:#a86a12;--up:#137a45;--dn:#c0392b;--sel:#fdf4e3}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:ui-monospace,"SF Mono",Menlo,monospace;
 font-variant-numeric:tabular-nums;font-size:13px;line-height:1.5;padding:26px 20px 60px}
.wrap{max-width:1580px;margin:0 auto}
h1{font-size:19px;margin:0 0 2px;font-weight:700}.sub{color:var(--dim);font-size:12px}
.prov{color:var(--faint);font-size:11px;margin-bottom:18px}
.hd{display:flex;align-items:center;gap:10px;margin:24px 0 9px}
.hd .k{color:var(--amber);font-size:10.5px;letter-spacing:.22em;text-transform:uppercase;white-space:nowrap}
.hd .k::before{content:"\258C";margin-right:7px}
.hd .r{flex:1;height:1px;background:var(--rule2)}
.warn{border:1px solid var(--dn);border-left:4px solid var(--dn);background:var(--panel);padding:13px 16px}
.warn .t{font-size:10px;letter-spacing:.16em;text-transform:uppercase;color:var(--dn);font-weight:700;margin-bottom:6px}
.warn b{color:var(--dn)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:10px;margin-top:8px}
.card{border:1px solid var(--rule2);background:var(--panel);padding:12px 14px}
.card.best{border-color:var(--up);border-left:4px solid var(--up)}
.card h3{margin:0 0 6px;font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:var(--amber)}
.card .big{font-size:26px;font-weight:700;line-height:1.1}
.card .l{font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--dim);margin-top:6px}
.card .s{font-size:11px;color:var(--faint);margin-top:2px}
.up{color:var(--up)}.dn{color:var(--dn)}.nil{color:var(--dim)}.am{color:var(--amber)}
.ctl{display:flex;flex-wrap:wrap;gap:16px;align-items:flex-end;border:1px solid var(--rule2);
 background:var(--panel);padding:12px 14px;margin-bottom:10px}
.ctl label{display:block;font-size:9.5px;letter-spacing:.16em;text-transform:uppercase;color:var(--dim);margin-bottom:5px}
.ctl input,.ctl select{font:inherit;font-size:14px;background:var(--panel2);color:var(--ink);
 border:1px solid var(--rule2);padding:6px 9px;border-radius:0}.ctl input{width:110px}
.ctl input:focus-visible,.ctl select:focus-visible{outline:2px solid var(--amber);outline-offset:1px}
.rid{font-family:var(--mono,ui-monospace,SFMono-Regular,Menlo,monospace);font-size:11px;
 letter-spacing:.06em;color:var(--dim)}
td.rid{white-space:nowrap}
.ctl button{font:inherit;font-size:12px;letter-spacing:.1em;text-transform:uppercase;cursor:pointer;
 background:var(--panel2);color:var(--dim);border:1px solid var(--rule2);padding:8px 12px;border-radius:0}
.ctl button:hover{color:var(--ink);border-color:var(--amber)}
.ctl button:focus-visible{outline:2px solid var(--amber);outline-offset:1px}
.hint{flex:1 1 230px;font-size:11px;color:var(--faint)}
.scroll{overflow:auto;max-height:620px;border:1px solid var(--rule2);background:var(--panel)}
table{border-collapse:collapse;width:100%;min-width:1420px;font-size:11.5px}
th,td{padding:6px 9px;text-align:right;white-space:nowrap;border-bottom:1px solid var(--rule)}
th{position:sticky;top:0;z-index:2;background:var(--panel2);color:var(--dim);font-size:9.5px;
 letter-spacing:.09em;text-transform:uppercase;font-weight:600;cursor:pointer;user-select:none}
th:hover{color:var(--amber)}th.l,td.l{text-align:left}
tbody tr{cursor:pointer}tbody tr:hover{background:var(--panel2)}
tbody tr.sel{background:var(--sel);box-shadow:inset 3px 0 0 var(--amber)}
tbody tr.fits{box-shadow:inset 3px 0 0 var(--up)}
tbody tr.rec{background:var(--sel);box-shadow:inset 4px 0 0 var(--up)}
/* TIGHT = stop at or under 1.00%. The operator asked where these were; they
   are in the grid, they just rarely survive, so they are marked to be found. */
tbody tr.dep{background:rgba(76,141,255,.13);box-shadow:inset 4px 0 0 #4c8dff}
.depbar{margin:10px 0 6px;padding:9px 12px;border-radius:6px;
  background:rgba(76,141,255,.10);border:1px solid rgba(76,141,255,.45);
  font-size:12.5px;line-height:1.55}
tbody tr.dep td{font-weight:600}
.tag.t-dep{background:#4c8dff;color:#04101f}
tbody tr.tight{background:rgba(240,168,72,.10);box-shadow:inset 4px 0 0 var(--amber)}
tbody tr.tight.rec{box-shadow:inset 4px 0 0 var(--up),inset 8px 0 0 var(--amber)}
.tag.t-tight{background:var(--amber);color:#160d02}
tbody tr.rec td{font-weight:600}
.tag.t-rec{background:var(--up);color:#04140b}
.recbox{border:1px solid var(--up);border-left:4px solid var(--up);background:var(--panel);
 padding:12px 15px;margin:8px 0 4px}
.recbox h3{margin:0 0 8px;font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:var(--up)}
.recbox .r{display:flex;justify-content:space-between;gap:12px;padding:5px 0;border-top:1px solid var(--rule)}
.recbox .r:first-of-type{border-top:0}
.recbox .why{color:var(--faint);font-size:11px}
.tag{display:inline-block;padding:1px 6px;font-size:9.5px;font-weight:700}
.t-f{background:var(--up);color:#04140b}.t-s{background:var(--amber);color:#160d02}
.t-x{color:var(--faint)}.t-liq{background:var(--dn);color:#fff}
.det{border:1px solid var(--rule2);background:var(--panel);margin-top:14px}
.det .top{padding:11px 14px;border-bottom:1px solid var(--rule2);display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}
.det .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(148px,1fr))}
.det .cell{padding:9px 14px;border-right:1px solid var(--rule);border-bottom:1px solid var(--rule)}
.det .cell .l{font-size:9.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--dim);margin-bottom:2px}
.det .cell .v{font-size:14px;font-weight:600}
/* A still-open trade is the LAST row of a log and the one most likely to be
   misread as a result, so it gets a left rail and a dimmed ground. */
.logbox tr.openrow{ background:rgba(148,163,184,.07) }
.logbox tr.openrow td:first-child{ box-shadow:inset 2px 0 0 #94a3b8 }
.logbox{max-height:380px;overflow:auto}.empty{padding:20px 14px;color:var(--faint);font-size:12px}
.note{border-left:2px solid var(--amber);background:var(--panel);padding:11px 15px;margin-top:16px;
 font-size:11.5px;color:var(--dim);line-height:1.75}.note b{color:var(--ink)}
@media(max-width:620px){body{padding:16px 10px 50px}}
</style>
<div class="wrap">
<h1>__TITLE__</h1>
<div class="sub">__SUB__</div>
<div class="prov" id="prov"></div>
<div class="depbar" id="depbar" style="display:none"></div>

<div class="warn">
  <div class="t">The trap, stated first</div>
  <span id="trapline">Win rate can be bought: put the target just past cost behind a wide stop and
  almost every trade wins while the account bleeds.</span> Win rate
  on its own is always purchasable. Every row below carries win rate <b>and</b> profit, and the
  answer is the best win rate among rows that <b>survive</b>.
</div>

<div class="hd"><span class="k">Best per coin and timeframe</span><span class="r"></span></div>
<div class="cards" id="cards"></div>

<div class="hd"><span class="k">Recommended</span><span class="r"></span></div>
<div id="recbox"></div>

<div class="hd"><span class="k">Controls</span><span class="r"></span></div>
<div class="ctl">
  <div><label for="base">Base margin USDT</label><input id="base" type="number" min="0.5" step="0.5" value="5"></div>
  <div><label for="wallet">Your wallet USDT</label><input id="wallet" type="number" min="10" step="5" value="65"></div>
  <div><label for="show">Show</label><select id="show">
    <option value="surv">survivors only</option>
    <option value="flat">flat survivors only</option>
    <option value="fits">survivors that fit the wallet</option>
    <option value="tight">TIGHT stops only (SL ≤ 1.00%)</option>
    <option value="prof">profitable</option>
    <option value="all">everything tested</option></select></div>
  <div><label for="coin">Coin</label><select id="coin">__COIN_OPTS__</select></div>
  <div><label for="tf">Timeframe</label><select id="tf">__TF_OPTS__</select></div>
  <div><label for="fwin">Min win rate %</label><input id="fwin" type="number" min="0" max="100" step="1" placeholder="any"></div>
  <div><label for="fprof">Min profit total $</label><input id="fprof" type="number" step="10" placeholder="any"></div>
  <div><label for="fgreen">Min months green</label><input id="fgreen" type="number" min="0" max="80" step="1" placeholder="any"></div>
  <div><label for="fdip">Max worst dip $</label><input id="fdip" type="number" min="0" step="5" placeholder="any"></div>
  <div><label for="fmon" title="re-runs every row over only the last N months or days of candles">Last N</label><input id="fmon" type="number" min="1" max="365" step="1" placeholder="all" style="width:70px"><select id="fmonu" title="window unit" style="font:inherit;font-size:14px;background:var(--panel2);color:var(--ink);border:1px solid var(--rule2);padding:6px 4px"><option value="m">months</option><option value="d">days</option></select></div>
  <div><label for="fid">Find row ID</label><input id="fid" type="text" placeholder="e.g. K4M7QP2X"></div>
  <div style="align-self:end"><button id="freset" type="button">clear filters</button></div>
  <div class="hint">LAST N (months or days) re-runs every row over just that slice of candles &mdash; profit, trades, wins, losses and win rate all become the window's own, not the year's.
    The DEPLOYED row always shows, whatever the Show box says.
    MIN MONTHS GREEN counts months, exactly as the GREEN column prints them: set 10 and a 9/12 row is gone.
    GREEN % is the same thing as a share, for sorting.
    Dollar figures re-simulate from the real candles when the base margin changes.
    A row is green-barred when its worst dip fits inside the wallet you type.</div>
</div>

<div class="hd"><span class="k">Grid</span><span class="r"></span><span class="k" style="color:var(--dim)" id="cnt"></span></div>
<div class="scroll"><table><thead><tr>
 <th data-k="id" title="stable row number — does not change when you sort or filter">ID</th>
 <th data-k="score" title="profitable + high win rate + consistent, minus drawdown">BALANCED</th>
 <th class="l" data-k="verdict">verdict</th>
 <th class="l" data-k="coin">coin</th><th class="l" data-k="tf">TF</th>
 <th class="l" data-k="signal">signal</th><th data-k="th">thresh %</th>
 <th data-k="sl">SL %</th><th data-k="tp">TP %</th><th data-k="rr">R:R</th>
 <th class="l" data-k="sizing">sizing</th><th data-k="lev">lev</th>
 <th data-k="trades">trades</th><th data-k="tpd">trades/day</th>
 <th data-k="wins">WINS</th><th data-k="losses">LOSSES</th>
 <th data-k="winrate">WIN %</th><th data-k="profit">PROFIT TOTAL $</th>
 <th data-k="this_month" id="thHdr">THIS MONTH $</th><th data-k="mtrades">mo trades</th>
 <th data-k="green">green</th><th data-k="dd">worst dip $</th>
 <th data-k="wstreak" title="the worst unbroken run of losses, added up — what a losing streak actually costs">worst streak $</th>
 <th data-k="wstreakn" title="how many losses in a row that streak was">streak losses</th>
 <th data-k="worst">worst single trade $</th><th data-k="cost_of_tp">cost/TP %</th>
 <th data-k="days">days</th>
 <th id="moHdrs" style="display:none"></th>
</tr></thead><tbody id="tb"></tbody></table></div>

<div class="det" id="det"><div class="empty">Select a row to replay every trade.</div></div>
<div class="note" id="foot"></div>
</div>
<script>
const D=__DATA__, LAD=D.ladder, DEC={d:-1,n:0,u:1};
/* Rows travel as arrays aligned to D.cols, not as 28,600 copies of the same
   twenty key names -- that alone was 13.3 MB of a 28.9 MB page, over the 16 MB
   artifact ceiling. Same coverage, a third of the bytes: every row still
   carries every field (kit item F), only the encoding shrank. */
if(D.cols){ const C=D.cols, n=C.length;
  D.rows = D.rows.map(a=>{ const o={}; for(let i=0;i<n;i++) o[C[i]]=a[i]; return o; }); }
/* Bar timestamps are perfectly regular, so they ship as (t0, step) instead of
   34,655 sixteen-character strings per frame -- another 4.9 MB. Materialised
   once, on first replay of that frame, and cached on the series itself. */
/* Direction arrays arrive run-length encoded ("n5u3" = five nothing, three
   long): 32% of the raw size, exactly reversible, expanded once per frame. */
function seriesD(s,key){
  if(!s._d) s._d={};
  if(s._d[key]!==undefined) return s._d[key];
  let v=s.d[key];
  if(v!==undefined && s.rle){
    let out=''; const re=/([udn])(\d*)/g; let m;
    while((m=re.exec(v))!==null) out+=m[1].repeat(m[2]?+m[2]:1);
    v=out;
  }
  s._d[key]=v; return v;
}
function seriesT(s){
  if(s.t) return s.t;
  const n=s.c.length, base=Date.parse(s.t0.replace(' ','T')+':00Z'), st=s.step*1000;
  const out=new Array(n);
  for(let i=0;i<n;i++) out[i]=new Date(base+i*st).toISOString().slice(0,16).replace('T',' ');
  s.t=out; return out;
}
D.rows.forEach(r=>{ if(r.mon){ const o={}; D.months.forEach((m,i)=>{
  const v=r.mon[i]; if(v!==null&&v!==undefined) o[m]=v; }); r.monthly=o; } });
const isDep=r=>(D.deployed||[]).some(d=>d.coin===r.coin&&d.tf===r.tf&&d.signal===r.signal
  &&Math.abs(d.sl-r.sl)<.01&&Math.abs(d.tp-r.tp)<.01&&d.sizing===r.sizing
  &&Math.abs(d.th-r.th)<.01);
let rows=D.rows.map(r=>({...r,dep:isDep(r),tight:r.sl<=1.0,
  ...Object.fromEntries(D.months.map(m=>['mo_'+m,(r.monthly||{})[m]])),
  greenpct: r.months?+(100*r.green/r.months).toFixed(1):null,
  tpd:+(r.trades/Math.max(r.days,1)).toFixed(2),
  this_month:+((r.monthly||{})[D.cur]||0).toFixed(2), mtrades:0}));
const isSurv=r=>r.profit>0&&r.h1>0&&r.h2>0&&r.months&&r.green/r.months>=.7&&r.gate!=='block'&&r.stop_reachable;
rows.forEach(r=>{r.surv=isSurv(r);});
const skey=r=>r.coin+'|'+r.tf;
/* BALANCED = profitable + high win rate + consistent, minus drawdown.
   Each axis is z-scored against the other SURVIVORS, so the number says
   "how far above the pack on this axis", not raw dollars. */
function scoreAll(){
  const sv=rows.filter(r=>r.surv).map(view);
  const z=(vals)=>{const m=vals.reduce((a,b)=>a+b,0)/vals.length;
    const sd=Math.sqrt(vals.reduce((a,b)=>a+(b-m)*(b-m),0)/vals.length)||1;
    return v=>(v-m)/sd;};
  const zp=z(sv.map(r=>r.profit)), zw=z(sv.map(r=>r.winrate)),
        zg=z(sv.map(r=>100*r.green/r.months)), zd=z(sv.map(r=>r.dd));
  const by=new Map();
  for(const r of sv) by.set([r.coin,r.tf,r.signal,r.th,r.sl,r.tp,r.sizing].join('|'),
    +(zp(r.profit)+zw(r.winrate)+zg(100*r.green/r.months)-zd(r.dd)).toFixed(4));
  for(const r of rows) r.score = r.surv
    ? by.get([r.coin,r.tf,r.signal,r.th,r.sl,r.tp,r.sizing].join('|')) : null;
  recommend();
}
/* The trap line is DERIVED from this grid's own rows — it once hardcoded
   "PI 1h reaches 92.2% and loses $80", which was false on every page except
   the one it was written for. */
(function(){
  const el=document.getElementById('trapline');
  if(!el||!rows.length)return;
  const t=rows.reduce((a,b)=>b.winrate>a.winrate?b:a);
  el.innerHTML=`The highest win rate in this grid is <b>${t.winrate.toFixed(1)}%</b>`
    +` (#${t.id} · ${t.tf} ${t.signal} · TP ${t.tp.toFixed(2)}% behind SL ${t.sl.toFixed(2)}%)`
    +` and it ${t.profit<0?'<b>loses money</b>: <b>−$'+Math.abs(t.profit).toFixed(2)+'</b>'
               :'makes only <b>+$'+t.profit.toFixed(2)+'</b>'}`
    +` over ${t.trades} trades. A tiny target behind a wide stop wins almost every`
    +` trade and one loss erases hundreds of wins.`;
})();
/* RECOMMENDED = survivor, top-20 by BALANCED, drawdown fits the wallet, and
   enough trades behind it. Max 3 — a list of ten is a ranking, not advice.

   The trade floor comes from the payload (D.rec_min_trades), defaulting to 100.
   A year of 15m produces ~795 trades for one config, so 100 filters nothing
   there and the 15m/30m sweep raises it to 300. Hardcoding 100 let a
   short-timeframe row earn the badge on a count that proves nothing. */
const REC_MIN_TRADES = (typeof D!=='undefined' && D.rec_min_trades) ? D.rec_min_trades : 100;
/* A history floor as well as a trade floor: MEXC serves 360 days of 15m for a
   mature contract and 166 for a younger one, and a "one year" sweep must not
   recommend the 166. */
const REC_MIN_DAYS = (typeof D!=='undefined' && D.rec_min_days) ? D.rec_min_days : 0;
function recommend(){
  const w=walletVal();
  rows.forEach(r=>{r.rec=false;r.why='';});
  const top=rows.filter(r=>r.surv).map(view).sort((a,b)=>(b.score??-9e9)-(a.score??-9e9)).slice(0,20);
  const ok=top.filter(r=>r.dd<w*0.5&&r.trades>=REC_MIN_TRADES
                        &&(r.days||0)>=REC_MIN_DAYS).slice(0,3);
  for(const v of ok){
    const r=rows.find(x=>x.coin===v.coin&&x.tf===v.tf&&x.signal===v.signal&&x.th===v.th
      &&x.sl===v.sl&&x.tp===v.tp&&x.sizing===v.sizing);
    if(!r)continue;
    r.rec=true;
    r.why = v.green===v.months ? v.green+'/'+v.months+' months green'
      : v.dd<w*0.35 ? 'dip only $'+v.dd.toFixed(2)+' on a $'+w+' wallet'
      : v.winrate>=55 ? v.winrate.toFixed(1)+'% win with '+v.trades+' trades'
      : 'best balance of profit, win rate and consistency';
  }
}
/* "Last N months" is not a row filter — filtering rows would leave a PROFIT
   column that still covered a year while the label claimed three months. It
   re-runs the strategy over only that slice of candles, so profit, trades,
   wins, losses, win rate, the streak and the dip are all the window's own. */
let WIN_MONTHS=0;
/* 'm' or 'd' — the operator runs this DAILY to see what is working right now,
   and "last 3 days" is a different question from "last 3 months". Same
   re-simulation either way; only the cut moves. */
let WIN_UNIT='m';
const winWord=()=>WIN_MONTHS+' '+(WIN_UNIT==='d'?'day':'month')+(WIN_MONTHS===1?'':'s');
function winCut(last){
  const cut=new Date(last.getTime());
  if(WIN_UNIT==='d') cut.setUTCDate(cut.getUTCDate()-WIN_MONTHS);
  else cut.setUTCMonth(cut.getUTCMonth()-WIN_MONTHS);
  return cut;}
/* A 3-month window starting mid-May reaches into 4 calendar months, so that is
   how many columns it gets: the operator asked for "3 months -> show 4 months",
   and no empty ones. A days window derives its month count from its own cut. */
const monthsShown=()=>{
  if(!WIN_MONTHS) return D.months;
  if(WIN_UNIT!=='d') return D.months.slice(0,WIN_MONTHS+1);
  const newest=D.months[0]; if(!newest) return D.months;
  const last=new Date(newest+'-28T00:00:00Z');
  const cut=winCut(last);
  const span=(last.getUTCFullYear()*12+last.getUTCMonth())
            -(cut.getUTCFullYear()*12+cut.getUTCMonth())+1;
  return D.months.slice(0,Math.max(1,span));};
const winVal=()=>{const q=parseInt((document.getElementById('fmon')||{}).value,10);
  return Number.isFinite(q)&&q>0?q:0;};
function winStart(t){
  if(!WIN_MONTHS||!t.length) return {i:0,from:t[0]};
  const last=new Date(t[t.length-1].replace(' ','T')+':00Z');
  const cut=winCut(last);
  const p=x=>String(x).padStart(2,'0');
  const key=`${cut.getUTCFullYear()}-${p(cut.getUTCMonth()+1)}-${p(cut.getUTCDate())} ${p(cut.getUTCHours())}:${p(cut.getUTCMinutes())}`;
  let lo=0,hi=t.length-1;                       // timestamps sort lexically
  while(lo<hi){const m=(lo+hi)>>1; if(t[m]<key)lo=m+1; else hi=m;}
  return {i:t[lo]<key?t.length-1:lo, from:key};
}
function replay(r,base){
  const s=D.series[skey(r)]; if(!s) return null;
  const o=s.o,h=s.h,l=s.l,c=s.c,t=seriesT(s),d=seriesD(s,r.signal+'|'+r.th),n=c.length;
  const W=winStart(t), i0=W.i;
  /* Funding, replayed the same way the engine does it: every settlement
     between the entry fill and the exit, at its own published rate. Without
     this the page's totals drift away from the grid's on exactly the rows that
     hold longest. */
  const FS=s.fund||[], FMS=FS.map(x=>x[0]);
  const FCUM=[0]; for(const x of FS) FCUM.push(FCUM[FCUM.length-1]+x[1]);
  const BMS=t.map(x=>Date.parse(x.replace(' ','T')+':00Z'));
  const fidx=v=>{let lo=0,hi=FMS.length; while(lo<hi){const m=(lo+hi)>>1;
    if(FMS[m]<=v)lo=m+1; else hi=m;} return lo;};
  const FEE=s.fee+D.slip, liq=s.liq/100, tp=r.tp/100, sl=r.sl/100;
  let step=0,trades=0,wins=0,liqs=0,profit=0,eq=0,peak=0,dd=0,worst=0;const log=[];
  /* A single bad trade is not what hurts on a ladder — a RUN of them is. Track the
     worst unbroken run of losses: what it cost, how many trades, and its dates. */
  let run=0,runN=0,runFrom=null,wRun=0,wRunN=0,wRunFrom=null,wRunTo=null;
  const monthly={}; let h1=0,h2=0; const mid=i0+Math.floor((n-i0)/2);
  let i=i0;
  while(i<n-1){
    const dir=DEC[d[i]]; if(!dir){i++;continue;}
    const margin=r.sizing==='flat'?base:base*LAD[Math.min(step,LAD.length-1)];
    const entry=o[i+1],notional=margin*D.lev;
    const tpPx=entry*(1+dir*tp),slPx=entry*(1-dir*sl),liqPx=entry*(1-dir*liq);
    let out=null,why=null,j=i+1;
    while(j<n){
      const hitLiq=dir===1?l[j]<=liqPx:h[j]>=liqPx;
      const hitSl=dir===1?l[j]<=slPx:h[j]>=slPx;
      if(hitLiq&&(liq<=sl||!hitSl)){out=-liq;why='LIQ';break;}
      if(hitSl){out=-sl;why='SL';break;}
      if(dir===1?h[j]>=tpPx:l[j]<=tpPx){out=tp;why='TP';break;}
      j++;
    }
    if(out===null){out=dir*(c[n-1]/entry-1);why='END';j=n-1;}
    let pnl=(out-2*FEE)*notional;
    const fund = FS.length ? -dir*(FCUM[fidx(BMS[j])]-FCUM[fidx(BMS[i+1])])*notional : 0;
    pnl += fund;
    if(why==='LIQ'){pnl=-margin;liqs++;}
    trades++; if(pnl>0)wins++;
    profit+=pnl;eq+=pnl;peak=Math.max(peak,eq);dd=Math.max(dd,peak-eq);worst=Math.min(worst,pnl);
    const mo=String(t[j]).slice(0,7);
    monthly[mo]=(monthly[mo]||0)+pnl;
    if(i<mid) h1+=pnl; else h2+=pnl;
    if(pnl>0){ run=0;runN=0;runFrom=null; }
    else{ if(!runN)runFrom=t[i+1]; run+=pnl; runN++;
          if(run<wRun){ wRun=run;wRunN=runN;wRunFrom=runFrom;wRunTo=t[j]; } }
    log.push({n:trades,open:t[i+1],close:t[j],side:dir>0?'LONG':'SHORT',rung:step+1,
      margin,notional,entry,tpPx,slPx,why,fund,pnl,run:eq});
    step=pnl>0?0:step+1;i=j+1;
  }
  const mkeys=Object.keys(monthly);
  return {trades,wins,losses:trades-wins,liqs,profit,worst,dd,log,
          wstreak:wRun,wstreakn:wRunN,wstreakFrom:wRunFrom,wstreakTo:wRunTo,
          monthly,green:mkeys.filter(k=>monthly[k]>0).length,months:mkeys.length,
          h1:+h1.toFixed(2),h2:+h2.toFixed(2),
          from:t[i0],to:t[n-1],
          days:Math.max(1,Math.round((new Date(t[n-1].replace(' ','T')+':00Z')
                -new Date(t[i0].replace(' ','T')+':00Z'))/86400000)),
          winrate:trades?100*wins/trades:0};
}
const f2=v=>(v>=0?'+':'')+v.toFixed(2), cls=v=>v>0?'up':v<0?'dn':'nil';
let sortK='score',dir=-1,sel=null,cache=null;
const baseVal=()=>Math.max(.5,parseFloat(document.getElementById('base').value)||5);
const walletVal=()=>Math.max(10,parseFloat(document.getElementById('wallet').value)||65);
/* Month trade counts need a replay. Doing all 11,440 on load is far too slow,
   so it is computed for the rows actually on screen and memoised. */
const _moCache=new Map();
function fillMonthTrades(list){
  for(const r of list){
    const k=[r.coin,r.tf,r.signal,r.th,r.sl,r.tp,r.sizing].join('|')+'|'+baseVal();
    let v=_moCache.get(k);
    if(!v){
      const x=(cache&&cache.get(r))||replay(r,baseVal());
      v = x ? {n:x.log.filter(t=>t.close.slice(0,7)===D.cur).length,
               ws:+x.wstreak.toFixed(2), wsn:x.wstreakn,
               from:x.wstreakFrom, to:x.wstreakTo}
            : {n:0,ws:0,wsn:0,from:null,to:null};
      _moCache.set(k,v);
    }
    r.mtrades=v.n; r.wstreak=v.ws; r.wstreakn=v.wsn;
    r.wstreakFrom=v.from; r.wstreakTo=v.to;
  }
}
function verdictOf(v){
  return !v.stop_reachable?'STOP UNREACHABLE':v.gate==='block'?'costs too much'
    :v.surv?(v.sizing==='flat'?'FLAT SURVIVOR':'survivor')
    :v.profit>0?'profitable':'rejected';}
function reverdict(){
  for(const r of rows){const v=view(r);
    r.surv=isSurv(v); r.verdict=verdictOf({...v,surv:r.surv});}}
function rescale(){const b=baseVal();
  if(b===D.base&&!WIN_MONTHS){cache=null;reverdict();return;}
  cache=new Map(); for(const r of rows){const x=replay(r,b); if(x)cache.set(r,x);}
  reverdict(); }
function view(r){const s=cache&&cache.get(r);
  if(!s) return r;
  const mo=s.log.filter(t=>t.close.slice(0,7)===D.cur);
  return {...r,base:baseVal(),notional:baseVal()*D.lev,profit:+s.profit.toFixed(2),
    dd:+s.dd.toFixed(2),worst:+s.worst.toFixed(2),
    wstreak:+s.wstreak.toFixed(2),wstreakn:s.wstreakn,
    wstreakFrom:s.wstreakFrom,wstreakTo:s.wstreakTo,
    greenpct:r.greenpct,
    trades:s.trades,wins:s.wins,losses:s.losses,
    winrate:+s.winrate.toFixed(2),liqs:s.liqs,
    green:s.green,months:s.months,h1:s.h1,h2:s.h2,days:s.days,
    greenpct:s.months?+(100*s.green/s.months).toFixed(1):null,
    tpd:+(s.trades/Math.max(s.days,1)).toFixed(2),
    ...Object.fromEntries(D.months.map(m=>['mo_'+m,s.monthly[m]])),
    this_month:+mo.reduce((a,t)=>a+t.pnl,0).toFixed(2), mtrades:mo.length};}
function filtered(){
  const v=document.getElementById('show').value,c=document.getElementById('coin').value,
        t=document.getElementById('tf').value,w=walletVal();
  const num=id=>{const e=document.getElementById(id); const q=e?parseFloat(e.value):NaN;
                 return Number.isFinite(q)?q:null;};
  const mnW=num('fwin'), mnP=num('fprof'), mnG=num('fgreen'), mxD=num('fdip');
  const idq=(document.getElementById('fid').value||'').toUpperCase().replace(/[^0-9A-Z]/g,'');
  /* Tolerant lookup: the code's length has changed once already, so a pasted
     6-character code must still find an 8-character row and vice versa. */
  if(idq) return rows.filter(r=>{const v=String(r.id).toUpperCase();
    return v===idq||v.endsWith(idq)||idq.endsWith(v);});
  return rows.filter(r=>{
    if(c&&r.coin!==c)return false; if(t&&r.tf!==t)return false;
    const x=view(r);
    if(mnW!==null&&x.winrate<mnW)return false;
    if(mnP!==null&&x.profit<mnP)return false;
    if(mnG!==null&&r.green<mnG)return false;          // count of green months, as the GREEN column prints it
    if(mxD!==null&&x.dd>mxD)return false;
    /* What is LIVE is never hidden by the Show dropdown. It is usually not a
       survivor, so "survivors only" would hide the one row the operator most
       needs to look up. Explicit number filters still apply. */
    if(r.dep)return true;
    if(v==='surv')return r.surv;
    if(v==='flat')return r.surv&&r.sizing==='flat';
    if(v==='fits')return r.surv&&x.dd<w*0.5;
    if(v==='tight')return r.tight;
    if(v==='prof')return x.profit>0;
    return true;});
}
function render(){
  const w=walletVal();
  buildMonthHeaders();
  const pre=filtered(); fillMonthTrades(pre);
  const list=pre.map(view).sort((a,b)=>{
    if(a.dep!==b.dep) return a.dep?-1:1;      // what is LIVE pins above all
    if(a.rec!==b.rec) return a.rec?-1:1;      // then recommendations
    const x=a[sortK],y=b[sortK];
    return typeof x==='string'?dir*String(x).localeCompare(String(y)):dir*((x??0)-(y??0));});
  const tag=r=>r.verdict==='FLAT SURVIVOR'?'<span class="tag t-f">FLAT SURVIVOR</span>'
   :r.verdict==='survivor'?'<span class="tag t-s">survivor</span>'
   :r.verdict==='STOP UNREACHABLE'?'<span class="tag t-liq">STOP UNREACHABLE</span>'
   :'<span class="tag t-x">'+r.verdict+'</span>';
  const idq=(document.getElementById('fid').value||'').toUpperCase().replace(/[^0-9A-Z]/g,'');
  const NCOL=document.querySelectorAll('thead th').length;
  document.getElementById('tb').innerHTML=list.length?list.map(r=>{
    const i=rows.findIndex(x=>x.coin===r.coin&&x.tf===r.tf&&x.signal===r.signal&&x.th===r.th
      &&x.sl===r.sl&&x.tp===r.tp&&x.sizing===r.sizing);
    return `<tr data-i="${i}" class="${r.dep?'dep ':''}${r.tight?'tight ':''}${r.rec?'rec':(r.surv&&r.dd<w*0.5?'fits':'')} ${sel===i?'sel':''}">
     <td class="rid">#${r.id}</td>
     <td class="am"><b>${r.score==null?'—':r.score.toFixed(2)}</b></td>
     <td class="l">${r.dep?'<span class="tag t-dep">◀ DEPLOYED</span> ':''}${r.rec?'<span class="tag t-rec">RECOMMENDED</span> ':''}${r.tight?'<span class="tag t-tight">TIGHT</span> ':''}${tag(r)}</td><td class="l"><b>${r.coin}</b></td><td class="l">${r.tf}</td>
     <td class="l">${r.signal}</td><td>${r.th.toFixed(1)}</td>
     <td>${r.sl.toFixed(2)}</td><td>${r.tp.toFixed(2)}</td><td>${r.rr.toFixed(2)}</td>
     <td class="l">${r.sizing}</td><td>${r.lev}x</td>
     <td>${r.trades}</td><td>${r.tpd.toFixed(2)}</td>
     <td class="up">${r.wins}</td><td class="dn">${r.losses}</td>
     <td class="am"><b>${r.winrate.toFixed(2)}</b></td>
     <td class="${cls(r.profit)}"><b>${f2(r.profit)}</b></td>
     <td class="${cls(r.this_month)}"><b>${f2(r.this_month)}</b></td>
     <td class="${r.mtrades<8?'nil':''}">${r.mtrades}</td>
     <td>${r.green}/${r.months}</td>
     <td class="${r.dd<w*0.5?'up':'dn'}">${r.dd.toFixed(2)}</td>
     <td class="dn"><b>${r.wstreak==null?'—':r.wstreak.toFixed(2)}</b></td><td>${r.wstreakn??'—'}</td>
     <td class="dn">${r.worst.toFixed(2)}</td>
     <td class="${r.gate==='ok'?'up':r.gate==='warn'?'am':'dn'}">${r.cost_of_tp.toFixed(1)}</td>
     <td>${r.days}</td>`
     + monthsShown().map(m=>{const v=r['mo_'+m];
         return v===undefined||v===null?'<td class="nil">—</td>'
           :`<td class="${cls(v)}">${f2(v)}</td>`;}).join('')
     + `</tr>`;}).join('')
    : `<tr><td class="l" colspan="${NCOL}" style="padding:22px 12px;color:var(--dim)">${
        idq ? 'No row #'+idq+' in this grid \u2014 '+rows.length+' rows, and a code is 8 characters.'
            : 'No row matches these filters. Loosen one \u2014 or press CLEAR FILTERS.'}</td></tr>`;
  const act=[['fwin','win \u2265','%'],['fprof','profit \u2265','$'],
             ['fgreen','green \u2265','mo'],['fdip','dip \u2264','$']]
    .map(([id,lab,u])=>{const q=parseFloat(document.getElementById(id).value);
      return Number.isFinite(q)?(u==='$'?lab+' $'+q
        :u==='mo'?lab+' '+q+' month'+(q===1?'':'s'):lab+' '+q+u):null;}).filter(Boolean);
  const wSpan=(()=>{ if(!WIN_MONTHS||!list.length) return '';
    const s0=cache&&cache.get(rows.find(r=>r.id===list[0].id));
    return s0 ? '  \u00b7  window: last '+winWord()
                +' ('+String(s0.from).slice(0,10)+' \u2192 '+String(s0.to).slice(0,10)+')' : '';})();
  const gq=parseFloat(document.getElementById('fgreen').value);
  const maxMo=Math.max(0,...rows.map(r=>r.months||0));
  const gNote = (Number.isFinite(gq)&&gq>maxMo)
    ? '  \u00b7  no coin here has '+gq+' months of history \u2014 the deepest is '+maxMo
    : '';
  document.getElementById('cnt').textContent = idq
    ? (list.length?'row #'+idq+' \u2014 other filters ignored'
                  :'no row #'+idq+' in this grid of '+rows.length)
    : list.length+' of '+rows.length+' shown'
      +(act.length?'  \u00b7  filters: '+act.join(' \u00b7 '):'')+gNote+wSpan;
  document.querySelectorAll('#tb tr').forEach(tr=>tr.addEventListener('click',()=>{sel=+tr.dataset.i;render();detail();}));
  cards();
}
function cards(){
  const b=baseVal(),w=walletVal();
  const out=[];
  /* Cards come from the DATA, never a hardcoded pair list: a coin/timeframe
     with no rows used to leave `trap` undefined and threw before any card was
     drawn, taking the whole page's detail panel with it. */
  /* One card per coin/timeframe reads well for a two-coin study and not at all
     for a market-wide one -- 447 coins produced 755 cards. Rank pairs by their
     best survivor, show the top few, and say how many were left out. */
  const CARD_CAP = (D.card_cap || 999);
  const bestOf=new Map();
  for(const r of rows){ if(!r.surv) continue; const k=r.coin+'|'+r.tf;
    if(!bestOf.has(k)||r.profit>bestOf.get(k)) bestOf.set(k,r.profit); }
  const allPairs=[...new Set(rows.map(r=>r.coin+'|'+r.tf))]
    .sort((a,b)=>(bestOf.get(b)??-9e9)-(bestOf.get(a)??-9e9));
  const pairs=allPairs.slice(0,CARD_CAP);
  for(const pr of pairs){
    const [coin,tf]=pr.split('|');
    const sub=rows.filter(r=>r.coin===coin&&r.tf===tf);
    const sv=sub.filter(r=>r.surv).map(view);
    const best=sv.slice().sort((a,b)=>b.winrate-a.winrate)[0];
    const bal=sv.slice().sort((a,b)=>(b.score??-9e9)-(a.score??-9e9))[0];
    const fl=sv.filter(r=>r.sizing==='flat').sort((a,b)=>b.winrate-a.winrate)[0];
    const fit=sv.filter(r=>r.dd<w*0.5).sort((a,b)=>b.winrate-a.winrate)[0];
    const trap=sub.slice().sort((a,b)=>b.winrate-a.winrate)[0];
    const m=D.meta[coin+'|'+tf]||{days:0,liq:0,rt:0};
    out.push(`<div class="card ${best&&best.winrate>=65?'best':''}">
      <h3>${coin} · ${tf}</h3>
      <div class="big am">${bal?f2(bal.profit):'—'}</div>
      <div class="s">${bal?'BALANCED pick · '+bal.signal+' SL '+bal.sl.toFixed(2)+'/TP '+bal.tp.toFixed(2)+' · '+bal.sizing+' · '+bal.winrate.toFixed(1)+'% win · '+bal.green+'/'+bal.months+' green · dip '+bal.dd.toFixed(2):'no survivors'}</div>
      <div class="l">highest win rate</div><div class="s">${best?best.winrate.toFixed(1)+'% · '+best.signal+' SL '+best.sl.toFixed(2)+'/TP '+best.tp.toFixed(2)+' · '+f2(best.profit):'none'}</div>
      <div class="l">best flat</div><div class="s">${fl?fl.winrate.toFixed(1)+'% · '+fl.signal+' SL '+fl.sl.toFixed(2)+'/TP '+fl.tp.toFixed(2)+' · '+f2(fl.profit):'none'}</div>
      <div class="l">fits ${w} wallet</div><div class="s">${fit?fit.winrate.toFixed(1)+'% · dip '+fit.dd.toFixed(2)+' · '+f2(fit.profit):'none — lower the base margin'}</div>
      <div class="l">survivors</div><div class="s">${sv.length} of ${sub.length} · ${m.days} days · liq ${(m.liq||0).toFixed(2)}% · cost ${m.rt==null?'book unreadable':m.rt.toFixed(3)+'%'}</div>
      <div class="l">best this month (${D.cur})</div><div class="s">${(()=>{const m=sv.slice().sort((a,b)=>b.this_month-a.this_month)[0];
        return m?f2(m.this_month)+' · '+m.signal+' SL '+m.sl.toFixed(2)+'/TP '+m.tp.toFixed(2)+' · '+m.mtrades+' trades':'none';})()}</div>
      <div class="l">up this month</div><div class="s">${sv.filter(x=>x.this_month>0).length} of ${sv.length} survivors</div>
      <div class="l">the trap</div><div class="s dn">${trap?trap.winrate.toFixed(1)+'% win → '+f2(view(trap).profit):'no rows'}</div>
    </div>`);
  }
  document.getElementById('cards').innerHTML=out.join('')
    + (allPairs.length>pairs.length
       ? `<div class="card" style="border-style:dashed"><h3>+ ${allPairs.length-pairs.length} more pairs</h3>
          <div class="s">not carded here, ranked below these by their best survivor.
          Every one is still in the grid — use the Coin box to pull it up.</div></div>` : '');
  const dep=rows.filter(r=>r.dep).map(view);
  const depHtml = dep.length
    ? `<div class="recbox" style="border-color:#4c8dff;border-left-color:#4c8dff;margin-bottom:8px">
        <h3 style="color:#4c8dff">Live right now — ${dep.length} deployed</h3>`
      + dep.map(r=>`<div class="r"><span><b><span class="rid">#${r.id}</span> ${r.coin} · ${r.tf} · ${r.signal}</b>
          <span class="why">threshold ${r.th.toFixed(1)}% · SL ${r.sl.toFixed(2)}% / TP ${r.tp.toFixed(2)}% · ${r.sizing} · ${r.lev}x · base $${r.base.toFixed(2)}</span><br>
          <span class="why">${r.verdict} · ${r.green}/${r.months} months green · ${r.trades} trades</span></span>
          <span style="text-align:right;white-space:nowrap"><span class="${cls(r.profit)}"><b>${f2(r.profit)}</b></span><br>
          <span class="why">${r.winrate.toFixed(1)}% win · dip $${r.dd.toFixed(2)}${r.dd>=walletVal()*0.5?' — over half your wallet':''}</span></span></div>`).join('')
      + `</div>` : '';
  const rec=rows.filter(r=>r.rec).map(view);
  document.getElementById('recbox').innerHTML = depHtml + (rec.length
    ? `<div class="recbox"><h3>Run these — ${rec.length} of ${rows.filter(r=>r.surv).length} survivors qualify</h3>`
      + rec.map(r=>`<div class="r"><span><b>${r.coin} · ${r.tf} · ${r.signal}</b>
          <span class="why">threshold ${r.th.toFixed(1)}% · SL ${r.sl.toFixed(2)}% / TP ${r.tp.toFixed(2)}% · ${r.sizing} · ${r.lev}x · base $${r.base.toFixed(2)}</span><br>
          <span class="why">${r.why}</span></span>
          <span style="text-align:right;white-space:nowrap"><span class="${cls(r.profit)}"><b>${f2(r.profit)}</b></span><br>
          <span class="why">${r.winrate.toFixed(1)}% win · ${r.trades} trades · dip $${r.dd.toFixed(2)}</span></span></div>`).join('')
      + `</div>`
    : `<div class="recbox" style="border-color:var(--dn);border-left-color:var(--dn)">
         <h3 style="color:var(--dn)">Nothing qualifies at a $${walletVal()} wallet and $${baseVal()} base</h3>
         <div class="why">A row must be a survivor, top-20 by BALANCED, have ${REC_MIN_TRADES}+ trades, and a drawdown
         under half your wallet. Lower the base margin — drawdown scales with it — and they will start
         qualifying.</div></div>`);
}
function detail(){
  const r=rows[sel],el=document.getElementById('det');
  if(!r){el.innerHTML='<div class="empty">Select a row to replay every trade.</div>';return;}
  const b=baseVal(),res=replay(r,b);
  /* A market-wide sweep cannot embed candles for every coin -- the page would
     be hundreds of megabytes. Rows whose coin was not embedded still carry
     every measured figure; they just cannot be replayed here. Say that, rather
     than throwing. */
  if(!res){
    el.innerHTML=`<div class="top"><div><b><span class="rid">#${r.id}</span> ${r.coin} · ${r.tf} · ${r.signal} · SL ${r.sl.toFixed(2)}% / TP ${r.tp.toFixed(2)}% · ${r.sizing}</b></div>
      <div class="${cls(r.profit)}"><b>TOTAL PROFIT ${f2(r.profit)} USDT</b></div></div>
      <div class="empty">Candles for ${r.coin} ${r.tf} are not embedded in this page, so its trades cannot be replayed here.
      Every figure in the row was measured in the sweep. Run this coin from the app's 1 YEAR button for a page with its full trade log.</div>`;
    el.scrollIntoView({behavior:'smooth',block:'start'});
    return;
  }
  const cell=(l,v,c='')=>`<div class="cell"><div class="l">${l}</div><div class="v ${c}">${v}</div></div>`;
  const m=D.meta[r.coin+'|'+r.tf]||{liq:0,days:r.days};
  el.innerHTML=`<div class="top">
    <div><b><span class="rid">#${r.id}</span> ${r.coin} · ${r.tf} · ${r.signal} · threshold ${r.th.toFixed(1)}% · SL ${r.sl.toFixed(2)}% / TP ${r.tp.toFixed(2)}% · ${r.sizing}</b>
      ${r.stop_reachable?'':' <span class="tag t-liq">STOP BEYOND LIQUIDATION</span>'}</div>
    <div class="${cls(res.profit)}"><b>TOTAL PROFIT ${f2(res.profit)} USDT</b></div></div>
   <div class="grid">
     ${cell('Win rate',res.winrate.toFixed(2)+'%','am')}
     ${cell('Trades',res.trades)}${cell('Wins',res.wins,'up')}${cell('Losses',res.losses,'dn')}
     ${cell('Liquidated',res.liqs||'none',res.liqs?'dn':'')}
     ${cell('Worst dip',res.dd.toFixed(2))}
     ${cell('Worst losing streak',res.wstreak.toFixed(2)+' over '+res.wstreakn+' trade'+(res.wstreakn===1?'':'s'),'dn')}
     ${cell('That streak ran',res.wstreakn?(String(res.wstreakFrom).slice(0,10)+' \u2192 '+String(res.wstreakTo).slice(0,10)):'\u2014')}
     ${cell('Worst single trade',res.worst.toFixed(2),'dn')}
     ${cell('1st half',f2(r.h1),cls(r.h1))}${cell('2nd half',f2(r.h2),cls(r.h2))}
     ${cell('Months green',r.green+'/'+r.months)}
     ${cell('Base margin',b.toFixed(2)+' USDT','am')}${cell('Notional',(b*D.lev).toFixed(2)+' USDT')}
     ${cell('Leverage',D.lev+'x')}${cell('Liquidation',m.liq.toFixed(2)+'%')}
     ${cell('Cost / TP',r.cost_of_tp.toFixed(1)+'%',r.gate==='ok'?'up':r.gate==='warn'?'am':'dn')}
     ${cell('History',r.days+' days')}
   </div>
   <div style="padding:9px 14px;border-bottom:1px solid var(--rule);font-size:11.5px">
     <span style="color:var(--dim);letter-spacing:.14em;text-transform:uppercase;font-size:9.5px">month by month</span><br>`
   + monthsShown().map(m=>{const v=(r.monthly||{})[m]; return v===undefined?'':
       `<span style="display:inline-block;min-width:112px"><span style="color:var(--faint)">${m}</span> `
       +`<span class="${cls(v)}">${f2(v)}</span></span>`;}).join('')
   + `</div>
   <div style="padding:10px 14px;border-bottom:1px solid var(--rule2);display:flex;
        justify-content:space-between;gap:10px;flex-wrap:wrap">
     <span style="color:var(--amber);font-size:10.5px;letter-spacing:.16em;text-transform:uppercase;font-weight:700">
       Past trades &middot; ${res.log.length}${WIN_MONTHS?' &middot; last '+winWord()+' only':''}</span>
     <span class="nil" style="font-size:11px">${res.log.length?res.log[0].open+' → '+res.log[res.log.length-1].close:''}
       &middot; median hold ${(()=>{const hs=res.log.map(t=>(new Date(t.close)-new Date(t.open))/3600000).sort((a,b)=>a-b);
         const m=hs.length?hs[Math.floor(hs.length/2)]:0; return m>=24?(m/24).toFixed(1)+'d':m.toFixed(1)+'h';})()}</span>
   </div>
   <div class="logbox"><table><thead><tr><th class="l">#</th><th class="l">OPENED</th><th class="l">CLOSED</th>
     <th class="l">HELD</th><th class="l">side</th><th class="l">closed by</th>
     <th>entry</th><th>exit</th><th>TP px</th><th>SL px</th><th>rung</th><th>margin $</th><th title="funding paid or received for holding">funding $</th>
     <th>PROFIT $</th><th>running $</th></tr></thead><tbody>`
   + res.log.map(t=>{const hh=(new Date(t.close)-new Date(t.open))/3600000;
     const ex=t.why==='TP'?t.tpPx:t.why==='SL'?t.slPx:null;
     // why==='END' means the CANDLES ran out with the position still open —
     // there was no exit. This cell used to print the last bar's timestamp
     // under a column headed CLOSED, so an open trade read as closed for a
     // profit it has not made. The operator caught it on row 181.
     const shut = t.why==='END'
       ? `<span class="nil">still open</span>` : t.close;
     return `<tr class="${t.why==='END'?'openrow':''}"><td class="l">${t.n}</td><td class="l">${t.open}</td><td class="l">${shut}</td>
     <td class="l">${hh>=24?(hh/24).toFixed(1)+'d':hh.toFixed(1)+'h'}</td>
     <td class="l">${t.side}</td><td class="l ${t.why==='LIQ'?'dn':''}"><b>${t.why}</b></td>
     <td>${t.entry.toFixed(6)}</td><td>${ex?ex.toFixed(6):'—'}</td>
     <td>${t.tpPx.toFixed(6)}</td><td>${t.slPx.toFixed(6)}</td>
     <td>${t.rung}</td><td>${t.margin.toFixed(2)}</td>
     <td class="${t.fund<0?'dn':t.fund>0?'up':'nil'}">${(t.fund||0).toFixed(3)}</td>
     <td class="${cls(t.pnl)}"><b>${f2(t.pnl)}</b></td><td class="${cls(t.run)}">${f2(t.run)}</td></tr>`;}).join('')
   + (()=>{
       // Split REALISED from OPEN. The engine marks a still-open trade to the
       // last close, charges it a full round trip and credits it as a win, so
       // the combined figure claimed money that is not banked yet.
       const op = res.log.filter(t=>t.why==='END');
       const opPnl = op.reduce((a,t)=>a+t.pnl,0);
       const rTrades = res.trades - op.length;
       const rWins = res.wins - op.filter(t=>t.pnl>0).length;
       const rLoss = res.losses - op.filter(t=>t.pnl<=0).length;
       const rProfit = res.profit - opPnl;
       const rWr = rTrades ? (rWins/rTrades*100) : 0;
       return `</tbody><tfoot><tr><td class="l" colspan="10">`
         + `REALISED · ${rTrades} closed trades · ${rWins}W / ${rLoss}L · `
         + `${rWr.toFixed(2)}% win</td>`
         + `<td class="${cls(rProfit)}"><b>${f2(rProfit)}</b></td><td></td></tr>`
         + (op.length ? `<tr><td class="l" colspan="10">`
             + `<span class="nil">STILL OPEN · ${op.length} trade`
             + `${op.length>1?'s':''} marked to the last close `
             + `(${op[0].close}) · not banked, can still hit its stop`
             + `</span></td><td class="${cls(opPnl)}">${f2(opPnl)}</td>`
             + `<td></td></tr>` : '')
         + `</tfoot></table></div>`;
     })();
  el.scrollIntoView({behavior:'smooth',block:'start'});
}
document.querySelectorAll('th').forEach(th=>th.addEventListener('click',()=>{
  const k=th.dataset.k;dir=(sortK===k)?-dir:-1;sortK=k;render();}));
['show','coin','tf'].forEach(id=>document.getElementById(id).addEventListener('change',()=>{sel=null;render();detail();}));
['fwin','fprof','fgreen','fdip'].forEach(id=>document.getElementById(id)
  .addEventListener('input',()=>{sel=null;render();detail();}));
document.getElementById('fid').addEventListener('input',()=>{
  const q=(document.getElementById('fid').value||'').toUpperCase().replace(/[^0-9A-Z]/g,'');
  const hit=q?rows.findIndex(r=>{const v=String(r.id).toUpperCase();
    return v===q||v.endsWith(q)||q.endsWith(v);}):-1;
  sel = hit>=0 ? hit : null;                 // a found row opens its own log
  render(); detail();
  if(hit>=0) document.getElementById('det').scrollIntoView({block:'nearest'});});
document.getElementById('freset').addEventListener('click',()=>{
  ['fwin','fprof','fgreen','fdip','fid','fmon'].forEach(id=>document.getElementById(id).value='');
  WIN_MONTHS=0; _moCache.clear(); rescale(); scoreAll();
  sel=null;render();detail();});
document.getElementById('wallet').addEventListener('input',()=>{recommend();render();});
document.getElementById('base').addEventListener('input',()=>{_moCache.clear();rescale();scoreAll();render();detail();});
document.getElementById('fmon').addEventListener('input',()=>{
  WIN_MONTHS=winVal(); _moCache.clear(); rescale(); scoreAll(); render(); detail();});
document.getElementById('fmonu').addEventListener('change',()=>{
  WIN_UNIT=document.getElementById('fmonu').value; WIN_MONTHS=winVal();
  _moCache.clear(); rescale(); scoreAll(); render(); detail();});
document.getElementById('thHdr').textContent=D.cur+' $';
/* One column per month, oldest on the right. EVERY row carries every month
   (payload stores them as an array aligned to D.months), so a blank cell means
   the coin had no history that month — never "dropped to save bytes". */
let _moHdrKey='';
function buildMonthHeaders(){
  const shown=monthsShown();
  const key=shown.join(',');
  if(key===_moHdrKey) return;
  _moHdrKey=key;
  const ph=document.getElementById('moHdrs');
  const hdr=ph?ph.parentElement:document.querySelector('thead tr');
  if(ph) ph.remove();
  hdr.querySelectorAll('th[data-k^="mo_"]').forEach(x=>x.remove());
  for(const m of shown){
    const e=document.createElement('th');
    e.dataset.k='mo_'+m; e.textContent=m.slice(2)+' $';
    e.title='profit in '+m;
    e.addEventListener('click',()=>{dir=(sortK===e.dataset.k)?-dir:-1;
      sortK=e.dataset.k; render();});
    hdr.appendChild(e);
  }
}
buildMonthHeaders();
document.getElementById('prov').innerHTML=__PROV__;
document.getElementById('foot').innerHTML=__FOOT__;
rescale();scoreAll();render();

/* The row the operator clicked BACKTEST on is what they came here to read, so
   the page says where it is instead of leaving them to hunt. It is already
   tinted, railed, tagged and pinned above every sort — this adds a line naming
   its ID and scrolls it into view, and opens its trade log if there is exactly
   one. Asked for on 2026-08-19: "when i backtest a strategy, highlight it in
   the results". */
(function announceDeployed(){
  const dep=rows.filter(r=>r.dep);
  const bar=document.getElementById('depbar');
  if(!bar) return;
  if(!dep.length){
    bar.innerHTML='<b>No row on this page is the deployed one.</b> Either the '
      + 'strategy is not armed, or its combination produced no trades in this '
      + 'window.';
    bar.style.display='block';
    return;
  }
  bar.innerHTML='<b>&#9664; DEPLOYED</b> &nbsp;'
    + dep.map(r=>'<b>#'+r.id+'</b> &mdash; '+r.coin+' '+r.tf+' '+r.signal
        +' SL '+r.sl.toFixed(2)+' / TP '+r.tp.toFixed(2)+' '+r.sizing
        +' &middot; '+(r.profit>=0?'+':'')+'$'+r.profit.toFixed(2)
        +' over '+r.trades+' trades'
        +(r.trades<(D.min_trades||30)
          ? ' <i>(below this page\'s '+(D.min_trades||30)
            +'-trade floor, kept because it is what you run)</i>' : ''))
      .join(' &nbsp;|&nbsp; ')
    + ' &nbsp;&mdash;&nbsp; highlighted in the table below, pinned above every '
    + 'sort.';
  bar.style.display='block';
  const tr=document.querySelector('tbody tr.dep');
  if(tr) tr.scrollIntoView({behavior:'smooth',block:'center'});
  if(dep.length===1){
    const i=rows.indexOf(dep[0]);
    if(i>=0){ sel=i; detail(); }
  }
})();
</script>
"""
