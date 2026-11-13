"""THE PICKER LAB'S RESULTS PAGE: every picker rule of a lab run (`v4_picker_lab.run`) as one page
with the standard kit (CLAUDE.md "Backtest reporting requirements").

    python -m tradingagents.v4_picker_lab page   ->  <v4 home>/picker-lab/page/index.html

One row per picker rule (its stable id first, `v4_picker_lab.rule_id`) plus one row for "no
picker", each carrying EVERY trade its three rooms made, in closing order:
[strategy, exit s, seconds held, profit x 10,000, exit kind, side, room, rule set followed].
Everything a row prints is worked out IN THE PAGE from those trades, so the base margin box
rescales every dollar (kit C), the last-N-days box re-adds every row over the trades OPENED in the
window - the day a picker chose them, the clock the lab walks on - and drops the month columns
outside it (kit G; a re-add of the measured trades, the picker is not started again, said beside
the count), and a click opens the trade-by-trade log with its TOTAL PROFIT (kit B, D). Max TP %
and max SL % are ceilings on every trade's own target and stop (the row prints the tightest to the
widest and the box cuts on the widest).

The page is refused when a row's trades are not the ones its figures were measured on (`_agree`).
The payload is gzipped and base64-encoded; a payload too big for one page goes into data files
beside it (`CHUNK`), which the page fetches - never trimmed.
"""
from __future__ import annotations

import base64
import gzip
import json
import pickle
from pathlib import Path

import numpy as np

CHUNK = 12_000_000        # characters a data file may hold (an artifact text file: 16 MB)
INLINE_MAX = 6_000_000    # a payload this size or smaller rides inside the page itself
FIELDS = ("s", "x", "h", "p", "y", "d", "q", "u")


def _before(prev: dict | None) -> dict | None:
    """The night before's run, as the page prints it beside tonight's: per rule its profit, trades,
    wins and the start days that made money."""
    if not prev:
        return None
    return {"end": prev["store"]["data_end_s"], "built_s": prev["built_s"], "days": prev["days"],
            "store_built_s": prev["store"].get("built_s"), "gaps": prev["store"].get("gaps"),
            "rows": {r["id"]: [r["profit"], r["trades"], r["win_rate"], r.get("starts_green"),
                               len(r.get("starts") or [])] for r in prev["rules"]}}


def payload(doc: dict, tp: dict, prev: dict | None = None) -> dict:
    """The page's data: every row with every field (kit F) and all its trades, compactly. `prev` is
    the kept run of an earlier night (`v4_picker_lab.previous`), shown beside each row."""
    from tradingagents import v4_store

    if tp.get("built_s") != doc.get("built_s"):
        raise ValueError("lab.json and trades.pkl are from two different runs: "
                         "python -m tradingagents.v4_picker_lab run")
    info = tp["info"]
    sids = sorted(info)
    s_ix = {s: i for i, s in enumerate(sids)}
    S = [[info[s][0], info[s][1], info[s][2], info[s][3], info[s][4],
          round(float(info[s][6]), 4), None if info[s][5] is None else round(float(info[s][5]), 4)] for s in sids]
    used = sorted({int(u) for t in tp["trades"].values() for u in np.unique(t["rset"])})
    u_ix = {u: i for i, u in enumerate(used)}
    U = [[tp["rules"][u]["id"], tp["rules"][u]["words"]] for u in used]
    by_id = {r["id"]: i for i, r in enumerate(tp["rules"])}
    rows, T = [], {}
    for r in doc["rules"]:
        t = tp["trades"][r["id"]]
        _agree(r, t)
        x = t["at"].astype(np.int64)
        T[r["id"]] = {"s": [s_ix[int(v)] for v in t["sid"]],
                      "x": np.diff(x, prepend=0).tolist(),              # exit seconds, each as a step on
                      "h": (x - t["en"]).tolist(), "p": t["p4"].tolist(),
                      "y": t["why"].tolist(), "d": (t["side"] > 0).astype(int).tolist(),
                      "q": t["slot"].tolist(), "u": [u_ix[int(v)] for v in t["rset"]]}
        rows.append({"id": r["id"], "key": r["key"], "name": r["name"], "baseline": bool(r["baseline"]),
                     "promote": r["promote"], "demote": r["demote"], "swaps": r["swaps"],
                     "empty": r["empty_room_days"], "first_pick_s": r["first_pick_s"],
                     "sets": [[u_ix[by_id[z["id"]]], z["room_days"], z["trades"], z["wins"], z["profit"]]
                              for z in r["rule_sets"]],
                     "rd": r["day_random"], "br": r["beat_random"], "sg": r["starts_green"],
                     "st": [[b["start_s"], b["days"], b["trades"], b["wins"], b["profit"]] for b in r["starts"]]})
    return {"base": doc["store"]["margin"], "lev": doc["store"]["leverage"],
            "day0": doc["first_day_s"], "days": doc["days"], "end": doc["store"]["data_end_s"],
            "walk_from": doc["walk"]["from_s"], "lead": doc["lead_days"], "slots": doc["slots"],
            "rule_sets": doc["rule_sets"], "tested": sum(not r["baseline"] for r in doc["rules"]),
            "random": doc["random"], "starts": doc["starts"], "coverage": doc["coverage"], "store": doc["store"],
            "built_s": doc["built_s"], "rooms": doc["rooms"], "whys": list(v4_store.WHYS),
            "prev": _before(prev),
            "S": S, "U": U, "rows": rows, "T": T}


def _agree(r: dict, t: dict) -> None:
    """A row's trades must be the trades its figures were measured on."""
    n, wins, profit = len(t["p4"]), int((t["p4"] > 0).sum()), float(t["p4"].sum()) / 1e4
    if n != r["trades"] or wins != r["wins"] or abs(profit - r["profit"]) > 0.0051:
        raise ValueError(f"#{r['id']}: its trades ({n}, {wins} won, {profit:+.2f}) are not the ones the "
                         f"run measured ({r['trades']}, {r['wins']} won, {r['profit']:+.2f}) - run the lab again")


def pack(data: dict) -> str:
    raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(gzip.compress(raw, 9, mtime=0)).decode("ascii")


def unpack(text: str) -> dict:
    return json.loads(gzip.decompress(base64.b64decode(text)))


def build(doc: dict, tp: dict, prev: dict | None = None) -> tuple[str, dict[str, str]]:
    """The page and the data files that go beside it ({} when the payload rides inside the page)."""
    z = pack(payload(doc, tp, prev))
    if len(z) <= INLINE_MAX:
        return _HTML.replace('const Z="";', f'const Z="{z}";', 1), {}
    files = {f"data-{k // CHUNK:03d}.txt": z[k:k + CHUNK] for k in range(0, len(z), CHUNK)}
    return _HTML.replace("const ZF=[];", f"const ZF={json.dumps(sorted(files))};", 1), files


def write(folder: Path | None = None) -> Path:
    """`index.html` (what is published: the artifact service adds the document around it),
    `preview.html` (the same page as a whole document, to open from a local server) and any data files."""
    from tradingagents import v4_picker_lab as lab

    root = Path(folder) if folder else lab.home()
    doc = json.loads((root / "lab.json").read_text(encoding="utf-8"))
    with open(root / "trades.pkl", "rb") as fh:
        tp = pickle.load(fh)
    html, files = build(doc, tp, lab.previous(doc))
    out = root / "page"
    out.mkdir(parents=True, exist_ok=True)
    for f in out.glob("data-*.txt"):
        f.unlink()
    for name, text in files.items():
        (out / name).write_text(text, encoding="ascii")
    (out / "index.html").write_text(html, encoding="utf-8")
    (out / "preview.html").write_text(
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"></head><body>' + html + "</body></html>",
        encoding="utf-8")
    return out / "index.html"


_HTML = r"""<title>Picker Rules Tested</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap">
<style>
/* layout: one working table under a provenance line and a strip of filters; a row opens its trade log */
:root{--bg:#f6f7f5;--panel:#fff;--ink:#15191a;--ink2:#4b5355;--ink3:#7a8386;--rule:#dde2df;
 --accent:#0f6b62;--gain:#2a78d6;--loss:#e34948;--warn:#9a6300;--tag:#e7efec;
 --sans:"Instrument Sans",system-ui,-apple-system,"Segoe UI",sans-serif;--mono:"JetBrains Mono",ui-monospace,Consolas,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#111514;--panel:#181d1c;--ink:#eef2f0;
 --ink2:#b3bcb9;--ink3:#86908d;--rule:#2b3331;--accent:#4fb3a7;--gain:#3987e5;--loss:#e66767;--warn:#e0a53a;--tag:#22302d}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#111514;--panel:#181d1c;--ink:#eef2f0;--ink2:#b3bcb9;--ink3:#86908d;
 --rule:#2b3331;--accent:#4fb3a7;--gain:#3987e5;--loss:#e66767;--warn:#e0a53a;--tag:#22302d}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 var(--sans)}
main{max-width:1500px;margin:0 auto;padding-block:16px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
h1{font-size:20px;margin:0 0 6px;text-wrap:balance}h3{margin:0 0 6px;font-size:16px;text-wrap:balance}
.prov,.count,.note{color:var(--ink2);font-size:13px;margin:6px 0;max-width:110ch}
.warn{border:1px solid var(--warn);border-radius:8px;padding:8px 12px;margin:10px 0;max-width:110ch;color:var(--ink);background:color-mix(in srgb,var(--warn) 10%,var(--panel))}
.filters{display:flex;flex-wrap:wrap;gap:8px 12px;margin:12px 0}
.filters label{display:flex;flex-direction:column;font-size:12px;color:var(--ink2)}
input,select,button{font:13px var(--sans);padding:4px 6px;border:1px solid var(--rule);border-radius:6px;background:var(--panel);color:var(--ink)}
button{cursor:pointer}button:disabled{cursor:default;color:var(--ink3)}
input:focus-visible,select:focus-visible,button:focus-visible,tr.row:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
input[type=number]{width:96px}.wrap{overflow-x:auto;background:var(--panel);border:1px solid var(--rule);border-radius:8px;min-width:0}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{padding:6px 8px;border-bottom:1px solid var(--rule);text-align:right;white-space:nowrap}
th{cursor:pointer;font-size:12px;color:var(--ink2);background:var(--panel)}
td.l,th.l{text-align:left}td.w{white-space:normal;min-width:240px;max-width:340px}
.id{font-family:var(--mono)}.pos{color:var(--gain)}.neg{color:var(--loss)}.muted{color:var(--ink3);font-style:italic}
.tag{display:inline-block;font-size:11px;padding:0 6px;border-radius:999px;background:var(--tag);color:var(--ink2);margin-left:6px}
tr.row:hover{background:color-mix(in srgb,var(--accent) 8%,transparent);cursor:pointer}
dialog{max-width:min(1200px,100vw - 32px);width:100%;border:1px solid var(--rule);border-radius:10px;background:var(--panel);color:var(--ink)}
dialog::backdrop{background:rgb(0 0 0 / .45)}
.sum{display:flex;flex-wrap:wrap;gap:6px 18px;margin:8px 0}.total{font-size:18px}
details{margin:6px 0;color:var(--ink2);font-size:13px}summary{cursor:pointer}
</style>
<main>
<h1 id="h">Picker rules, tested</h1>
<p class="warn" id="warn" hidden></p>
<p class="prov" id="prov">Opening the trades…</p>
<div class="filters">
 <label>Base margin $<input id="f-base" type="number" min="0.1" step="0.5"></label>
 <label>Min win %<input id="f-wr" type="number" min="0" max="100" placeholder="any"></label>
 <label>Min profit $<input id="f-pr" type="number" step="1" placeholder="any"></label>
 <label>Min months green<input id="f-gm" type="number" min="0" step="1" placeholder="any"></label>
 <label>Max worst dip $<input id="f-dd" type="number" min="0" step="1" placeholder="any"></label>
 <label>Max TP %<input id="f-tp" type="number" min="0" step="0.1" placeholder="any"></label>
 <label>Max SL %<input id="f-sl" type="number" min="0" step="0.1" placeholder="any"></label>
 <label>Last N days<input id="f-days" type="number" min="1" step="1" placeholder="all days"></label>
 <label>Find by ID<input id="f-id" type="text" placeholder="#XXXXXXXX"></label>
 <label>&nbsp;<button id="clear">Clear all filters</button></label>
</div>
<p class="count" id="count"></p>
<div class="wrap"><table><thead id="thead"></thead><tbody id="tbody"></tbody></table></div>
<div id="notes"></div>
</main>
<dialog id="dlg"><div id="dlg-body"></div><p><button id="dlg-close">Close</button></p></dialog>
<script>
const Z="";
const ZF=[];
const MON=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
function fmtWhen(ms){const d=new Date(ms);let h=d.getHours();const ap=h<12?"am":"pm";h=h%12||12;
 return `${MON[d.getMonth()]} ${String(d.getDate()).padStart(2,"0")}, ${d.getFullYear()} ${h}:${String(d.getMinutes()).padStart(2,"0")}${ap}`}
/*LOGIC*/
const usd=v=>"$"+Math.abs(v).toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2});
const money=v=>v==null?"":(v>0?"+":"")+(v<0?"-":"")+usd(v);
// a row's trades out of their compact columns: exit seconds were stored as steps, the entry as seconds held
function decode(c){const n=c.p.length,ex=new Int32Array(n),en=new Int32Array(n);let t=0;
 for(let i=0;i<n;i++){t+=c.x[i];ex[i]=t;en[i]=t-c.h[i]}
 return {n,ex,en,p:Int32Array.from(c.p),s:Int32Array.from(c.s),y:Uint8Array.from(c.y),d:Uint8Array.from(c.d),q:Uint8Array.from(c.q),u:Int32Array.from(c.u)}}
// a month is the UTC month a trade OPENED in - the day the picker chose its rule set, the clock the test walks on
function monthKey(s){const d=new Date(s*1000);return `${d.getUTCFullYear()}-${String(d.getUTCMonth()+1).padStart(2,"0")}`}
function monthList(D){const out=[],last=monthKey(D.day0+(D.days-1)*86400);let [y,m]=monthKey(D.day0).split("-").map(Number);
 for(;;){const key=`${y}-${String(m).padStart(2,"0")}`;out.push(key);if(key>=last)break;m++;if(m>12){m=1;y++}}
 return out}
// the window a "last N days" box means, in whole picker days: it starts where the test starts when N is longer
function windowOf(D,days){const n=days&&days<D.days?days:D.days;const skip=D.days-n;
 return {days:n,skip,from:skip?D.day0+skip*86400:null,start:D.day0+skip*86400,clamped:!!days&&days>D.days}}
// one row over the trades OPENED at or after from_s (null = all), dollars x k. In closing order: the worst losing
// run is the unbroken run of losses with the biggest sum, the worst dip the furthest the running total fell from
// its high. stop / target are the WIDEST among its trades (target null when any trade has none).
function measure(t,S,from_s,k){
 let n=0,wins=0,profit=0,gw=0,gl=0,run=0,runN=0,worst=0,worstN=0,cum=0,peak=0,dip=0,noTgt=false,sLo=null,sHi=null,gLo=null,gHi=null;
 const months={},idx=[];
 const endRun=()=>{if(runN&&run<worst){worst=run;worstN=runN}run=0;runN=0};
 for(let i=0;i<t.n;i++){if(from_s!=null&&t.en[i]<from_s)continue;idx.push(i);
  const p=t.p[i]/1e4*k;n++;profit+=p;
  if(t.p[i]>0){wins++;gw+=p;endRun()}else{gl-=p;run+=p;runN++}
  cum+=p;if(cum>peak)peak=cum;if(peak-cum>dip)dip=peak-cum;
  const m=monthKey(t.en[i]);months[m]=(months[m]||0)+p;
  const st=S[t.s[i]],sl=st[5],tp=st[6];
  sLo=sLo==null?sl:Math.min(sLo,sl);sHi=sHi==null?sl:Math.max(sHi,sl);
  if(tp==null)noTgt=true;else{gLo=gLo==null?tp:Math.min(gLo,tp);gHi=gHi==null?tp:Math.max(gHi,tp)}}
 endRun();
 const losses=n-wins,aw=wins?gw/wins:null,al=losses?gl/losses:null;
 return {trades:n,wins,losses,win:n?wins/n*100:null,profit:n?profit:null,per:n?profit/n:null,aw,al,
  be:aw!=null&&al!=null&&aw+al>0?al/(aw+al)*100:null,ratio:aw!=null&&al?aw/al:null,
  worst,worstN,dip,months,green:n?Object.values(months).filter(v=>v>0).length:null,
  stop:n?sHi:null,stopLeast:n?sLo:null,target:n&&!noTgt?gHi:null,targetLeast:gLo,targetMost:gHi,noTgt,idx};
}
// the filters a measured row fails, by name (inclusive; a row with no trade has no number to meet any of them)
function fails(m,f){const out=[];
 if(f.wr!=null&&!(m.win!=null&&m.win>=f.wr))out.push("min win %");
 if(f.pr!=null&&!(m.profit!=null&&m.profit>=f.pr))out.push("min profit $");
 if(f.gm!=null&&!(m.green!=null&&m.green>=f.gm))out.push("min months green");
 if(f.dd!=null&&!(m.trades>0&&m.dip<=f.dd))out.push("max worst dip $");
 if(f.tp!=null&&!(m.target!=null&&m.target<=f.tp))out.push("max TP %");
 if(f.sl!=null&&!(m.stop!=null&&m.stop<=f.sl))out.push("max SL %");
 return out}
function filterNames(f){const w={wr:v=>`win at least ${v}%`,pr:v=>`profit at least ${money(v)}`,gm:v=>`${v} or more months green`,
 dd:v=>`worst dip no deeper than ${usd(v)}`,tp:v=>`target at most ${v}% on every trade`,sl:v=>`stop at most ${v}% on every trade`};
 return Object.keys(w).filter(k=>f[k]!=null).map(k=>w[k](f[k]))}
const perDay=(n,span)=>(n/span).toFixed(2);
// a blank sorts last both ways
function sortVal(x,c){const m=x.m,r=x.r,t=m.trades;
 const v={profit:m.profit,win:m.win,wins:t?m.wins:null,losses:t?m.losses:null,trades:t||null,perday:t||null,per:m.per,
  aw:m.aw,al:m.al,ratio:m.ratio,be:m.be,worst:t?m.worst:null,dip:t?-m.dip:null,green:m.green,tp:m.target,sl:m.stop,
  swaps:r.swaps,empty:r.empty,rs:x.rs,edge:t&&x.rs!=null?m.profit-x.rs:null,bp:r.br.in_profit?r.br.in_profit[1]:null,
  sg:r.st.length?r.sg/r.st.length:null,sets:r.sets.length,prevp:x.pv&&x.pv[1]?x.pv[0]*x.k:null,prevw:x.pv&&x.pv[1]?x.pv[2]:null};
 return c in v?v[c]:String(r[c]??"")}
function sortRows(xs,k,dir){return [...xs].sort((a,b)=>{const p=sortVal(a,k),q=sortVal(b,k);if(p==null&&q==null)return 0;if(p==null)return 1;if(q==null)return -1;
 return (typeof p==="number"&&typeof q==="number"?p-q:String(p).localeCompare(String(q)))*dir})}
/*END LOGIC*/
const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const pct=v=>v==null?"":(+v.toFixed(2))+"%";
const rng=(lo,hi)=>lo==null||hi==null?"":(Math.abs(hi-lo)<1e-9?pct(hi):pct(lo)+" to "+pct(hi));
const num=s=>{const v=parseFloat(s);return Number.isFinite(v)?v:null};
const LOG_PAGE=100;
let D=null,T={};
const state={base:5,f:{},days:null,id:"",opened:"",cur:"",log:0,sort:{k:"profit",dir:-1}};
const idKey=()=>state.id.replace(/^#/,"").toUpperCase();
const COLS=[["id","ID",1],["name","Picker rule",1],["profit","PROFIT (total $)"],["prevp","PROFIT the night before $"],["win","Win %"],["prevw","Win % the night before"],["wins","W"],["losses","L"],
 ["trades","Trades"],["perday","Trades a day"],["wlday","W / L a day"],["per","$ a trade"],["aw","Average win $"],["al","Average loss $"],
 ["ratio","Win ÷ loss size"],["be","Break-even win %"],["worst","Worst losing run"],["dip","Worst dip $"],["green","Months green"],
 ["tp","TP % (target on every trade)"],["sl","SL % (stop on every trade)"],["lev","Leverage",1],["sets","Rule sets followed"],
 ["swaps","Times a room dropped its rule set"],["empty","Room-days sitting empty"],["sg","Start days that made money"],
 ["rs","Random strategies $"],["edge","$ above random strategies"],["bp","Beat random pickers ($ a trade)"]];
function view(){const w=windowOf(D,state.days),k=state.base/D.base,all=monthList(D);
 const months=w.from==null?all:all.filter(m=>{const [y,mo]=m.split("-").map(Number);return Date.UTC(y,mo,1)/1000>w.from});
 const rows=D.rows.map(r=>{const m=measure(T[r.id],D.S,w.from,k);
  return {r,m,k,pv:D.prev?D.prev.rows[r.id]||null:null,rs:r.rd.slice(w.skip).reduce((a,b)=>a+b,0)*k}});
 let shown;const id=idKey();
 if(id)shown=rows.filter(x=>x.r.id===id);else shown=rows.filter(x=>!fails(x.m,state.f).length);
 return {rows,shown,months,w,k}}
function cellOf(x,c,v){const r=x.r,m=x.m,span=v.w.days;const why='<span class="muted">no trade in this window</span>';
 switch(c){case"id":return `<span class="id">#${esc(r.id)}</span>`;
  case"name":return esc(r.name)+(r.baseline?'<span class="tag">no picker</span>':"");
  case"profit":return m.trades?`<b class="${m.profit>0?"pos":"neg"}">${money(m.profit)}</b>`:why;
  case"prevp":return !D.prev?'<span class="muted">no earlier run kept</span>':!x.pv?'<span class="muted">not in that run</span>':x.pv[1]?`<span class="${x.pv[0]>0?"pos":"neg"}">${money(x.pv[0]*v.k)}</span>`:'<span class="muted">no trade</span>';
  case"prevw":return !D.prev?'<span class="muted">no earlier run kept</span>':!x.pv?'<span class="muted">not in that run</span>':x.pv[1]?x.pv[2].toFixed(1)+"%":'<span class="muted">no trade</span>';
  case"win":return m.win!=null?m.win.toFixed(1)+"%":why;case"wins":return m.trades?m.wins.toLocaleString("en-US"):why;
  case"losses":return m.trades?m.losses.toLocaleString("en-US"):why;case"trades":return m.trades?m.trades.toLocaleString("en-US"):why;
  case"perday":return m.trades?perDay(m.trades,span):why;case"wlday":return m.trades?`${perDay(m.wins,span)} / ${perDay(m.losses,span)}`:why;
  case"per":return m.trades?`<span class="${m.per>0?"pos":"neg"}">${money(m.per)}</span>`:why;
  case"aw":return m.aw!=null?money(m.aw):(m.trades?'<span class="muted">no win</span>':why);
  case"al":return m.al!=null?money(-m.al):(m.trades?'<span class="muted">no loss</span>':why);
  case"ratio":return m.ratio!=null?m.ratio.toFixed(2)+" to 1":(m.trades?'<span class="muted">needs a win and a loss</span>':why);
  case"be":return m.be!=null?m.be.toFixed(1)+"%":(m.trades?'<span class="muted">needs a win and a loss</span>':why);
  case"worst":return m.trades?(m.worstN?`${money(m.worst)} over ${m.worstN}`:"no losses"):why;
  case"dip":return m.trades?(m.dip>0?money(-m.dip):"none"):why;
  case"green":return m.trades?`${m.green}/${v.months.length}`:why;
  case"tp":return m.trades?(m.target!=null?rng(m.targetLeast,m.target):(m.targetMost!=null?rng(m.targetLeast,m.targetMost)+", some with no target":"no target")):why;
  case"sl":return m.trades?rng(m.stopLeast,m.stop):why;case"lev":return D.lev+"x";
  case"sets":return r.sets.length;case"swaps":return r.swaps;case"empty":return `${r.empty} of ${D.days*D.slots}`;
  case"rs":return m.trades?money(x.rs):why;
  case"edge":return m.trades?`<span class="${m.profit-x.rs>0?"pos":"neg"}">${money(m.profit-x.rs)}</span>`:why;
  case"sg":return `${r.sg} of ${r.st.length}`;
  case"bp":return r.br.in_profit==null?'<span class="muted">no trade</span>':`${r.br.in_profit[1]} of ${D.random.runs}`}}
const LIMITS={wr:"min win %",pr:"min profit $",gm:"min months green",dd:"max worst dip $",tp:"max TP %",sl:"max SL %"};
function render(){const v=view();const s=state.sort;v.shown=sortRows(v.shown,s.k,s.dir);
 $("thead").innerHTML="<tr>"+COLS.map(([c,l,left])=>`<th data-k="${c}" class="${left?"l":""}">${esc(l)}${s.k===c?(s.dir>0?" ▲":" ▼"):""}</th>`).join("")
  +v.months.map(m=>`<th>${MON[+m.slice(5)-1]} ${m.slice(0,4)} $</th>`).join("")+"</tr>";
 $("tbody").innerHTML=v.shown.map(x=>`<tr class="row" tabindex="0" data-id="${esc(x.r.id)}">`+COLS.map(([c,_l,left])=>`<td class="${left?"l":""}${c==="name"?" w":""}">${cellOf(x,c,v)}</td>`).join("")
  +v.months.map(m=>{const p=x.m.months[m];return `<td class="${p>0?"pos":p<0?"neg":""}">${p==null?'<span class="muted">no trade</span>':money(p)}</td>`}).join("")+"</tr>").join("");
 const names=filterNames(state.f),id=idKey(),w=v.w;
 const idle=Object.keys(LIMITS).filter(key=>state.f[key]!=null&&v.rows.every(x=>!fails(x.m,{[key]:state.f[key]}).length))
  .map(key=>`${LIMITS[key]} cuts nothing here: every row already meets it`);
 const none=Object.keys(LIMITS).filter(key=>state.f[key]!=null&&v.rows.every(x=>fails(x.m,{[key]:state.f[key]}).length)).map(key=>{
  if(key==="sl"){const lo=Math.min(...v.rows.filter(x=>x.m.trades).map(x=>x.m.stop));return `max SL % cuts every row: each one's rooms took trades with a stop wider than ${state.f.sl}% (the tightest row's widest stop is ${pct(lo)})`}
  if(key==="tp"){const ok=v.rows.filter(x=>x.m.target!=null);return ok.length?`max TP % cuts every row: the smallest "widest target" is ${pct(Math.min(...ok.map(x=>x.m.target)))}`:"max TP % cuts every row: each one's rooms took some trades that have no target at all"}
  return `${LIMITS[key]} cuts every row`});
 const noTarget=state.f.tp!=null?v.rows.filter(x=>x.m.trades&&x.m.target==null).length:0;
 $("count").innerHTML=`<b>${v.shown.length}</b> of ${D.rows.length} rows (${D.tested} picker rules and the rooms with no picker)`
  +(id?(v.shown.length?" · found by ID (the other filters are off)":` · no row has #${esc(id)} (the other filters are off)`):"")
  +(names.length&&!id?" · "+esc(names.join(" AND ")):"")
  +` · trades opened ${fmtWhen(w.start*1000)} to ${fmtWhen(D.end*1000)} (${w.days} days)`
  +(state.days?(w.clamped?` · last ${state.days} days is longer than the ${D.days} days tested: all of them`:" · every row re-added from its own trades opened in these days (the picker is not started again: each room keeps the rule set it was following)"):"")
  +` · at ${usd(state.base)} margin a trade`+(state.base!==D.base?` (scaled from the ${usd(D.base)} measured)`:"")
  +(noTarget&&!none.length?` · max TP % leaves out ${noTarget} row(s) whose rooms took trades with no target`:"")
  +(idle.length?" · "+esc(idle.join("; ")):"")+(none.length&&!id?" · "+esc(none.join("; ")):"")
  +(!v.shown.length&&!id?` · all ${D.rows.length} rows were checked, every trade of each`:"");
 drawProv(v);
 document.querySelectorAll("#thead th").forEach(th=>th.onclick=()=>{const k=th.dataset.k;if(!k)return;state.sort={k,dir:state.sort.k===k?-state.sort.dir:-1};render()});
 document.querySelectorAll("#tbody tr").forEach(tr=>{tr.onclick=()=>open(tr.dataset.id);tr.onkeydown=e=>{if(e.key==="Enter")open(tr.dataset.id)}})}
function open(id){state.cur=id;state.log=0;drawLog(true)}
function drawLog(show){const v=view(),x=v.rows.find(y=>y.r.id===state.cur);if(!x)return;const r=x.r,m=x.m,t=T[r.id],ix=m.idx;
 const pages=Math.max(1,Math.ceil(ix.length/LOG_PAGE));state.log=Math.min(Math.max(state.log,0),pages-1);
 const a=state.log*LOG_PAGE,b=Math.min(ix.length,a+LOG_PAGE);let run=0;
 for(let j=0;j<a;j++)run+=t.p[ix[j]]/1e4*v.k;
 const sets=r.sets.map(([u,days,n,w,p])=>`<tr><td class="l"><span class="id">#${esc(D.U[u][0])}</span></td><td class="l w">${esc(D.U[u][1])}</td><td>${days}</td><td>${n.toLocaleString("en-US")}</td><td>${n?(w/n*100).toFixed(1)+"%":""}</td><td class="${p>0?"pos":p<0?"neg":""}">${money(p*v.k)}</td></tr>`).join("");
 $("dlg-body").innerHTML=`<h3><span class="id">#${esc(r.id)}</span> ${esc(r.name)}</h3>
 <p class="note"><b>Picks:</b> ${esc(r.promote)} <b>Drops:</b> ${esc(r.demote)}</p>
 <div class="sum"><span>TOTAL PROFIT <b class="total ${m.profit>0?"pos":"neg"}">${m.trades?money(m.profit):"$0.00"}</b></span>
 <span>${m.trades.toLocaleString("en-US")} trades · ${m.wins.toLocaleString("en-US")} won · ${m.losses.toLocaleString("en-US")} lost${m.win!=null?" · "+m.win.toFixed(1)+"%":""}</span>
 <span>worst losing run <b>${m.worstN?`${money(m.worst)} over ${m.worstN}`:"none"}</b></span><span>worst dip <b>${m.dip>0?money(-m.dip):"none"}</b></span>
 <span>${m.be!=null?`needs ${m.be.toFixed(1)}% wins to break even (average win ${money(m.aw)}, average loss ${money(-m.al)})`:""}</span></div>
 <p class="note">${D.slots} rooms, each $${state.base} margin x ${D.lev}x a trade. ${r.first_pick_s?`First pick ${fmtWhen(r.first_pick_s*1000)}.`:"It never found a rule set that passed."} A room dropped its rule set ${r.swaps} time(s); rooms sat empty on ${r.empty} of ${D.days*D.slots} room-days. Random strategies on the same days (the same number of trades at the average trade of the same kind): ${money(x.rs)}.${r.br.in_profit==null?"":` Against ${D.random.runs} pickers drawing blindly among rule sets that had made money, it made more a trade than ${r.br.in_profit[1]} and more in total than ${r.br.in_profit[0]}; against pickers drawing among any rule set that trades, ${r.br.any[1]} and ${r.br.any[0]}.`}</p>
 <details open><summary>Started afresh on ${r.st.length} different days: it made money from ${r.sg} of them (whole test, empty rooms each time)</summary>
 <div class="wrap"><table><thead><tr><th class="l">Started</th><th>Days</th><th>Trades</th><th>Win %</th><th>Profit</th><th>Profit a day</th></tr></thead><tbody>${r.st.map(([s0,dn,n,w,p])=>`<tr><td class="l">${fmtWhen(s0*1000)}</td><td>${dn}</td><td>${n.toLocaleString("en-US")}</td><td>${n?(w/n*100).toFixed(1)+"%":'<span class="muted">no trade</span>'}</td><td class="${p>0?"pos":p<0?"neg":""}">${n?money(p*v.k):'<span class="muted">no trade</span>'}</td><td>${n?money(p*v.k/dn):""}</td></tr>`).join("")}</tbody></table></div></details>
 <details${r.sets.length<=8?" open":""}><summary>The ${r.sets.length} rule set(s) its rooms followed, whole test</summary>
 <div class="wrap"><table><thead><tr><th class="l">Rule set</th><th class="l">What it switches on</th><th>Room-days</th><th>Trades</th><th>Win %</th><th>Profit</th></tr></thead><tbody>${sets}</tbody></table></div></details>
 <p class="note">Trades ${ix.length?a+1:0}-${b} of ${ix.length.toLocaleString("en-US")}, in the order they closed <button id="log-prev"${state.log?"":" disabled"}>Previous ${LOG_PAGE}</button> <button id="log-next"${state.log<pages-1?"":" disabled"}>Next ${LOG_PAGE}</button> (the total above is every trade, not this page)</p>
 <div class="wrap"><table><thead><tr><th class="l">#</th><th class="l">Room</th><th class="l">Rule set</th><th class="l">Coin</th><th class="l">Chart</th><th class="l">Strategy</th><th class="l">Side</th><th class="l">In</th><th class="l">Out</th><th class="l">Exit</th><th>SL %</th><th>TP %</th><th>Profit</th><th>Running</th></tr></thead><tbody>
 ${ix.slice(a,b).map((i,j)=>{const p=t.p[i]/1e4*v.k,st=D.S[t.s[i]];run+=p;return `<tr><td class="l">${a+j+1}</td><td class="l">${t.q[i]+1}</td><td class="l"><span class="id">#${esc(D.U[t.u[i]][0])}</span></td><td class="l">${esc(st[1])}</td><td class="l">${esc(st[2])}</td><td class="l">${esc(st[3])} <span class="id">#${esc(st[0])}</span></td><td class="l">${t.d[i]?"long":"short"}</td><td class="l">${fmtWhen(t.en[i]*1000)}</td><td class="l">${fmtWhen(t.ex[i]*1000)}</td><td class="l">${esc(D.whys[t.y[i]])}</td><td>${pct(st[5])}</td><td>${st[6]==null?"none":pct(st[6])}</td><td class="${p>0?"pos":"neg"}">${money(p)}</td><td>${money(run)}</td></tr>`}).join("")}
 </tbody></table></div>`;
 $("log-prev").onclick=()=>{state.log--;drawLog(false)};$("log-next").onclick=()=>{state.log++;drawLog(false)};
 if(show)$("dlg").showModal();$("dlg").scrollTop=0}
function drawProv(v){const k=v.k,sh=D.random.shelves,rp=sh.in_profit.profit,ra=sh.any.profit,cov=Object.entries(D.coverage).map(([tf,c])=>c.first_s?`${tf} from ${fmtWhen(c.first_s*1000)}`:`${tf}: none`).join(", ");
 $("prov").innerHTML=`<b>${D.tested}</b> picker rules tested, each choosing rule sets for <b>${D.slots}</b> rooms among <b>${D.rule_sets.toLocaleString("en-US")}</b> Forecast v4 rule sets, one pick a day at 12:00am UTC from trades that had already closed, over <b>${D.days}</b> days (${fmtWhen(D.day0*1000)} to ${fmtWhen(D.end*1000)}; the ${D.lead} days before were only watched). Every trade is <b>${usd(state.base)}</b> margin x <b>${D.lev}x</b> = <b>${usd(state.base*D.lev)}</b> of coin${k!==1?` (scaled from the ${usd(D.base)} measured)`:""}, after the exchange's fee both ways, ${D.store.gaps?"the coin's usual buy-sell gap (the middle of its recorded minutes over 30 days)":"one reading of the coin's buy-sell gap, taken the night the store was measured,"} and funding; no trade paid its own minute's order book (100% typical cost), and none was refused by the cost check. Luck: ${D.random.runs} pickers that drew blindly among rule sets that had made money over their last 30 days made a middle ${money(rp[1]*k)} (most between ${money(rp[0]*k)} and ${money(rp[2]*k)}), ${sh.in_profit.in_profit} of ${D.random.runs} in profit; drawing among any rule set that trades, a middle ${money(ra[1]*k)}, ${sh.any.in_profit} in profit. Measured ${fmtWhen(D.built_s*1000)} on the store built ${fmtWhen(D.store.built_s*1000)} (${D.store.strategies.toLocaleString("en-US")} strategies, ${D.store.trades.toLocaleString("en-US")} trades). Practice money only: nothing here was switched on.`;
 $("notes").innerHTML=`<details open><summary>How to read this</summary>
 <p class="note">A trade counts on the day it was OPENED, the day the picker chose its rule set; days and months are UTC (the first day began ${fmtWhen(D.day0*1000)} on your clock). "Random strategies" is the same number of trades on the same days, each worth the average trade of every strategy of the same kind that day. "Beat random pickers" counts how many of ${D.random.runs} pickers that drew rule sets blindly (from those with 30+ trades closed in their last 30 days that made money over them, redrawn every ${D.random.hold} days) made less a trade: the test a picker rule's ORDER has to pass, since every blind pick was also making money. "Start days that made money" starts the same rule afresh, with empty rooms, on ${D.starts.length} different days, 7 days apart, from ${fmtWhen(D.starts[0]*1000)} to ${fmtWhen(D.starts[D.starts.length-1]*1000)}, and counts the starts that ended in profit: a rule that holds what it picked on day one is otherwise judged on a single pick. SL % and TP % show the tightest to the widest stop and target among a row's trades, and the max SL % / max TP % boxes cut on the widest.${D.prev?` The two "night before" columns are the same rule measured on the store that ended ${fmtWhen(D.prev.end*1000)} (run ${fmtWhen(D.prev.built_s*1000)}, its whole test of ${D.prev.days} days): they do not follow the last-N-days box.`:""}</p>
 <p class="note">What the stored trades cover: ${esc(cov)}. The store keeps a fixed number of candles for each chart size, so the short charts only reach back a few weeks: before those dates no rule set could be built on them, and the early days of this test were picked from the longer charts alone.</p>
 <p class="note">Not in the test: the live picker also drops a rule set when its room loses money in practice (there is no practice record for past days). Each room is its own account, so two rooms following rule sets that share a strategy both take its trade. Twenty rules were tried on one stretch of ${D.days} days, so the best of them is partly luck: trust a rule more when every month is green and it beats most random pickers.</p></details>`}
// what to read first: how this store priced each coin's gap, and whether the night before agrees
function warning(){const g=D.store.gaps,p=D.prev,out=[];const made=rows=>rows.filter(x=>x[1]&&x[0]>0).length;
 if(!g)out.push("This store priced every coin's whole past with ONE reading of its buy-sell gap, taken as the machines ran that night. Another night reads another gap, so the same rules can give different results from one night's store to the next.");
 else out.push(`This store priced ${g.minutes||0} coin(s) with their usual gap (the middle of their recorded minutes over 30 days)${g["one reading"]?` and ${g["one reading"]} coin(s) with one reading of the book (no minute recorded for them)`:""}.`);
 if(p){const now=D.rows.filter(r=>!r.baseline),a=made(now.map(r=>{const t=T[r.id];let s=0;for(let i=0;i<t.n;i++)s+=t.p[i];return [s,t.n]})),b=made(now.map(r=>p.rows[r.id]||[0,0]));
  out.push(`The same ${now.length} rules on the store that ended ${fmtWhen(p.end*1000)}: ${b} made money. On this one, which ended ${fmtWhen(D.end*1000)}: ${a} made money. Trust a rule only where both nights agree (the "night before" columns).`)}
 else out.push("No run on an earlier night's store is kept yet, so there is nothing to check these results against.");
 return out.join(" ")}
function wire(){state.base=D.base;$("f-base").value=D.base;$("warn").textContent=warning();$("warn").hidden=false;
 for(const [el,key] of [["f-wr","wr"],["f-pr","pr"],["f-gm","gm"],["f-dd","dd"],["f-tp","tp"],["f-sl","sl"]])$(el).addEventListener("input",e=>{state.f[key]=num(e.target.value);render()});
 $("f-base").addEventListener("input",e=>{const v=num(e.target.value);state.base=v&&v>0?v:D.base;render()});
 $("f-days").addEventListener("input",e=>{const v=num(e.target.value);state.days=v&&v>0?Math.floor(v):null;render()});
 // find by ID opens that row's log once per new match: only this box opens it, never a later render
 $("f-id").addEventListener("input",e=>{state.id=e.target.value.trim();render();const id=idKey();
  if(id&&D.rows.some(r=>r.id===id)){if(state.opened!==id){state.opened=id;open(id)}}else state.opened=""});
 $("clear").onclick=()=>{state.f={};state.days=null;state.id="";state.opened="";state.base=D.base;$("f-base").value=D.base;
  for(const el of ["f-wr","f-pr","f-gm","f-dd","f-tp","f-sl","f-days","f-id"])$(el).value="";render()};
 $("dlg-close").onclick=()=>$("dlg").close();
 $("h").textContent=`${D.tested} picker rules, tested over ${D.days} days`;render()}
async function inflate(b64){const bin=Uint8Array.from(atob(b64),c=>c.charCodeAt(0));
 const s=new Blob([bin]).stream().pipeThrough(new DecompressionStream("gzip"));return JSON.parse(await new Response(s).text())}
async function load(){if(!ZF.length)return inflate(Z);
 const parts=await Promise.all(ZF.map(f=>fetch(f).then(r=>{if(!r.ok)throw new Error(f+": HTTP "+r.status);return r.text()})));return inflate(parts.join(""))}
if(typeof document!=="undefined")load().then(d=>{D=d;for(const [id,c] of Object.entries(D.T))T[id]=decode(c);delete D.T;wire()})
 .catch(e=>{$("prov").textContent="The page's data could not be opened: "+e});
</script>
"""
