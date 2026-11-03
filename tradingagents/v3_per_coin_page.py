"""THE BACKTEST V3 PER-COIN RESULTS PAGE (Nov 03, 2026): every coin x idea row of a per-coin
publish (`v3_per_coin`) as one artifact page with the standard kit (CLAUDE.md "Backtest reporting
requirements").

    python -m tradingagents.v3_per_coin_page <name>  ->  stores.V3.home/pages/<name>-per-coin.html

Built from the run's newest kept per-coin copy and the records in its folder, never from anything
typed. One row per coin x judged group, profitable or not (kit F), its stable id first
(`v3_per_coin.row_id`), each carrying its chosen setting's UNSEEN trades so every figure is worked
out IN THE PAGE from them: the risk box rescales every dollar (the research measured at $5 a trade),
the "last N days" box re-adds every row over the trades that CLOSED in it and drops the month
columns outside it (no minutes ride in a page, so it is a re-add of the measured trades, never a
new walk - said beside the count), max TP % and max SL % are ceilings on every trade's own target
and stop, and a click opens the row's trade log with its TOTAL PROFIT. Above the table: how many
rows were judged, how many are profitable, and how many the random runs would make profitable by
the same rule (each row's share, added up) - over every row, and over the rows the filters show.

The payload is compressed in its ENCODING, never by dropping a field (kit F): rows are arrays
aligned to one header (`F`), each trade [entry minute after the split, minutes held, side, exit
kind, profit x 10,000, stop x 100,000 or -1, target x 100,000 or -1], and the whole is gzipped
and base64-encoded into the page, which inflates it in the browser (`DecompressionStream`).
"""
from __future__ import annotations

import argparse
import base64
import gzip
import json
import re
from pathlib import Path

STORE_VERSION = 1        # v3_per_coin.VERSION; another version is refused by name
WHYS = ("TP", "SL", "TRAIL", "MA", "TIME", "END", "RANK")
# a row's fields, in the order its array holds them
FIELDS = ("id", "coin", "kind", "family", "tf", "filter", "setting", "verdict", "profitable",
          "blank", "target_rule", "stop_rule", "lev", "notional", "older", "random_median",
          "luck_share", "luck_profitable", "random_runs", "cost_unseen", "cost_older",
          "cost_share", "days", "trades", "profit")


def _trades(rec: dict, row: dict, split_ms: int) -> list[list[int]]:
    from tradingagents import v3_families as vf

    if not row["setting"]:
        return []
    key = vf.combo_key(row["family"], row["setting"], row["tf"], row["filter"])
    base = split_ms // 60_000
    out = []
    for r in rec.get("combos", {}).get(key, {}).get("unseen", {}).get("rows") or []:
        e, x = int(r[1]) // 60_000, int(r[2]) // 60_000
        out.append([e - base, x - e, int(r[3]), WHYS.index(r[5]), int(round(float(r[4]) * 10_000)),
                    int(round(float(r[6]) * 100_000)) if len(r) > 6 and r[6] is not None else -1,
                    int(round(float(r[7]) * 100_000)) if len(r) > 7 and r[7] is not None else -1])
    out.sort(key=lambda t: (t[0] + t[1], t[0]))
    return out


def _agree(row: dict, trades: list) -> None:
    """A row's trades must be the trades its verdict was judged on - the same count and the same
    profit to the rounding of the encoding - or the page would print numbers that disagree with
    PROFITABLE: refused, never warned (the pooled page's rule, RCA-2026-10-28-E)."""
    n = int(row["trades"] or 0)
    profit = sum(t[4] for t in trades) / 10_000
    said = float(row["profit"] or 0.0)
    if len(trades) != n or abs(profit - said) > 0.005 + n * 0.00005:
        raise ValueError(f"{row['id']} {row['coin']}: the run folder now holds trades the "
                         f"verdicts were not judged on ({len(trades)} trades, {profit:+.2f}, "
                         f"against the row's {n}, {said:+.2f}) - publish the per-coin verdicts "
                         "again")


def payload(store: dict, records: list[dict]) -> dict:
    """The page's data, decoded: every row with every field and its unseen trades."""
    if store.get("version") != STORE_VERSION or store.get("kind") != "per_coin":
        raise ValueError(f"per-coin store version {store.get('version')}: this page reads version "
                         f"{STORE_VERSION} (python -m tradingagents.v3_per_coin publish <name>)")
    by = {r["coin"]: r for r in records}
    gone = sorted({r["coin"] for r in store["rows"]} - set(by))
    if gone:
        raise ValueError(f"{', '.join(gone)}: the run folder no longer holds the record the rows "
                         "were judged on - publish the per-coin verdicts again")
    rows, trades = [], []
    for row in store["rows"]:
        t = _trades(by[row["coin"]], row, int(store["plan_split"]))
        _agree(row, t)
        flat = {**row, "profitable": 1 if row["profitable"] else 0,
                "older": " · ".join(f"{k}: {n} older trades" + (
                    "" if p is None else f", {p:+.4f} a trade") for k, (n, p) in
                    row["older"].items()),
                "cost_unseen": row["cost"]["unseen"], "cost_older": row["cost"]["older"],
                "cost_share": row["cost"]["share"]}
        rows.append([flat[f] for f in FIELDS])
        trades.append(t)
    return {"name": store["name"], "venue": store.get("venue") or "", "risk": store["risk_usd"],
            "runs": store["runs"], "tried": store["tried"], "groups": store["groups"],
            "plan_id": store["plan_id"], "plan_kind": store.get("plan_kind") or "universe",
            "start": store["plan_start"], "split": store["plan_split"], "end": store["plan_end"],
            "judged_at": store["judged_at"], "coins": len(store["coins"]),
            "plan_coins": store["plan_coins"], "dispatched": store.get("dispatched"),
            "rule": store["rule"], "min_older": store["min_older"],
            "min_unseen": store["min_unseen"], "totals": store["totals"],
            "not_judged": store.get("not_judged") or {}, "accounts": store.get("accounts") or {},
            "github_runs": store.get("github_runs") or {}, "notes": store.get("notes") or [],
            "whys": list(WHYS), "F": list(FIELDS), "R": rows, "T": trades}


def pack(data: dict) -> str:
    """The payload as the page embeds it: JSON, gzipped, base64."""
    raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(gzip.compress(raw, 9, mtime=0)).decode("ascii")


def unpack(html: str) -> dict:
    """The payload back out of a built page (what the browser inflates)."""
    blob = re.search(r'const Z="([A-Za-z0-9+/=]*)";', html).group(1)
    return json.loads(gzip.decompress(base64.b64decode(blob)).decode("utf-8"))


def build(store: dict, records: list[dict]) -> str:
    return _HTML.replace('const Z="";', f'const Z="{pack(payload(store, records))}";', 1)


def write(name: str) -> Path:
    """The page of the run `name`'s newest kept per-coin verdicts, under the v3 store."""
    from tradingagents import (
        stores,
        v3_cloud as vc,
        v3_per_coin as vpc,
        v3_research as vrs,
        v3_results_page as vrp,
        v3_universe as vu,
    )

    store = json.loads(vrp.newest_kept(name, vpc.history_dir(),
                                       "python -m tradingagents.v3_per_coin publish")
                       .read_text(encoding="utf-8"))
    sp = vc._state_path(store["name"])
    if not sp.exists():
        raise ValueError(f"no run named {store['name']}: python -m tradingagents.v3_cloud dispatch "
                         f"{store['name']}")
    plan = vu.load(json.loads(sp.read_text(encoding="utf-8"))["plan_copy"])
    if plan["id"] != store["plan_id"]:
        raise ValueError(f"the plan copy of {store['name']} is plan {plan['id']}, the rows were "
                         f"judged under {store['plan_id']}")
    records, _other = vrs.split_records(vrs.load_coins(vrs.home(store["folder"])), plan,
                                        store["runs"], store["risk_usd"])
    out = Path(stores.V3.home) / "pages" / f"{name}-per-coin.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(store, records), encoding="utf-8")
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m tradingagents.v3_per_coin_page")
    p.add_argument("name")
    a = p.parse_args(argv)
    out = write(a.name)
    print(f"{out} ({out.stat().st_size / 1e6:.1f} MB)")
    return 0


_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Backtest v3 Per Coin</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap">
<style>
:root{color-scheme:light;--bg:#f6f7f5;--panel:#fff;--ink:#15191a;--ink2:#4b5355;--ink3:#7a8386;--rule:#dde2df;
 --accent:#0f6b62;--gain:#2a78d6;--loss:#e34948;--warn:#9a6300;
 --sans:"Instrument Sans",system-ui,-apple-system,"Segoe UI",sans-serif;--mono:"JetBrains Mono",ui-monospace,Consolas,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#111514;--panel:#181d1c;--ink:#eef2f0;
 --ink2:#b3bcb9;--ink3:#86908d;--rule:#2b3331;--accent:#4fb3a7;--gain:#3987e5;--loss:#e66767;--warn:#e0a53a}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#111514;--panel:#181d1c;--ink:#eef2f0;--ink2:#b3bcb9;--ink3:#86908d;
 --rule:#2b3331;--accent:#4fb3a7;--gain:#3987e5;--loss:#e66767;--warn:#e0a53a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 var(--sans)}
main{max-width:1400px;margin:0 auto;padding:16px}h1{font-size:20px;margin:0 0 6px}
.prov,.count,.note{color:var(--ink2);font-size:13px;margin:6px 0}.head{font-size:15px;margin:10px 0}
.filters{display:flex;flex-wrap:wrap;gap:8px 12px;margin:12px 0}
.filters label{display:flex;flex-direction:column;font-size:12px;color:var(--ink2)}
input,select,button{font:13px var(--sans);padding:4px 6px;border:1px solid var(--rule);border-radius:6px;background:var(--panel);color:var(--ink)}
input[type=number]{width:96px}.wrap{overflow-x:auto;background:var(--panel);border:1px solid var(--rule);border-radius:8px}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{padding:6px 8px;border-bottom:1px solid var(--rule);text-align:right;white-space:nowrap}
th{cursor:pointer;font-size:12px;color:var(--ink2);position:sticky;top:0;background:var(--panel)}
td.l,th.l{text-align:left}.id{font-family:var(--mono)}.pos{color:var(--gain)}.neg{color:var(--loss)}.muted{color:var(--ink3);font-style:italic}
tr.row:hover{background:color-mix(in srgb,var(--accent) 8%,transparent);cursor:pointer}
dialog{max-width:min(1100px,100vw - 32px);width:100%;border:1px solid var(--rule);border-radius:10px;background:var(--panel);color:var(--ink)}
.sum{display:flex;flex-wrap:wrap;gap:6px 18px;margin:8px 0}.total{font-size:18px}.pager{display:flex;gap:8px;align-items:center;margin:8px 0}
</style></head><body><main>
<h1 id="h">Backtest v3, coin by coin</h1>
<p class="prov" id="prov">Opening the data...</p>
<p class="head" id="head"></p>
<div class="filters">
 <label>Risk a trade $<input id="f-risk" type="number" min="0.1" step="0.5"></label>
 <label>Profitable only<select id="f-pass"><option value="">all rows</option><option value="1">profitable</option></select></label>
 <label>Min win %<input id="f-wr" type="number" min="0" max="100" placeholder="any"></label>
 <label>Min win ÷ loss size<input id="f-ratio" type="number" min="0" step="0.1" placeholder="any"></label>
 <label>Min profit $<input id="f-pr" type="number" step="1" placeholder="any"></label>
 <label>Min months green<input id="f-gm" type="number" min="0" step="1" placeholder="any"></label>
 <label>Max worst dip $<input id="f-dd" type="number" min="0" step="1" placeholder="any"></label>
 <label>Max TP %<input id="f-tp" type="number" min="0" step="0.1" placeholder="any"></label>
 <label>Max SL %<input id="f-sl" type="number" min="0" step="0.1" placeholder="any"></label>
 <label>Last N days<input id="f-days" type="number" min="1" step="1" placeholder="all unseen"></label>
 <label>Coin<input id="f-coin" type="text" placeholder="any"></label>
 <label>Find by ID<input id="f-id" type="text" placeholder="#XXXXXXXX"></label>
 <label>&nbsp;<button id="clear">Clear all filters</button></label>
</div>
<p class="count" id="count"></p>
<div class="pager"><button id="p-prev">Previous 100</button><span id="p-at"></span><button id="p-next">Next 100</button></div>
<div class="wrap"><table><thead id="thead"></thead><tbody id="tbody"></tbody></table></div>
<div class="note" id="notes"></div>
<p class="note" id="legend"></p>
</main>
<dialog id="dlg"><div id="dlg-body"></div><p><button id="dlg-close">Close</button></p></dialog>
<script>
const Z="";
const MON=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
function fmtWhen(ms){const d=new Date(ms);let h=d.getHours();const ap=h<12?"am":"pm";h=h%12||12;
 return `${MON[d.getMonth()]} ${String(d.getDate()).padStart(2,"0")}, ${d.getFullYear()} ${h}:${String(d.getMinutes()).padStart(2,"0")}${ap}`}
/*LOGIC*/
const usd=v=>"$"+Math.abs(v).toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2});
const money=v=>v==null?"":(v>0?"+":"")+(v<0?"-":"")+usd(v);
// the rows as objects, each trade [entry s, exit s, side, exit kind, profit x 1e4, stop x 1e5, target x 1e5]
function rowsOf(D){const split=Math.floor(D.split/60000)*60;
 return D.R.map((a,i)=>{const r={};D.F.forEach((f,j)=>r[f]=a[j]);
  r.t=D.T[i].map(x=>{const e=split+x[0]*60;return [e,e+x[1]*60,x[2],x[3],x[4],x[5],x[6]]});return r})}
// one row over the trades that CLOSED at or after from_s (null = every unseen trade), dollars x k
function measure(r,from_s,k){
 const t=from_s==null?r.t:r.t.filter(x=>x[1]>=from_s);
 let profit=0,wins=0,winSum=0,lossSum=0,run=0,runN=0,worst=0,worstN=0,noStop=false,noTgt=false,sLo=null,sHi=null,gLo=null,gHi=null;const months={};
 for(const x of t){const p=x[4]/1e4*k;profit+=p;
  if(p>0){wins++;winSum+=p;run=0;runN=0}else{lossSum-=p;run+=p;runN++;if(run<worst){worst=run;worstN=runN}}
  const m=monthKey(x[1]);months[m]=(months[m]||0)+p;
  if(x[5]>=0){const v=x[5]/1e3;sLo=sLo==null?v:Math.min(sLo,v);sHi=sHi==null?v:Math.max(sHi,v)}else noStop=true;
  if(x[6]>=0){const v=x[6]/1e3;gLo=gLo==null?v:Math.min(gLo,v);gHi=gHi==null?v:Math.max(gHi,v)}else noTgt=true}
 const n=t.length,losses=n-wins,aw=wins?winSum/wins:null,al=losses?lossSum/losses:null;
 return {trades:n,wins,losses,win:n?wins/n*100:null,profit:n?profit:null,per:n?profit/n:null,avgWin:aw,avgLoss:al,
  ratio:aw!=null&&al?aw/al:null,worst:worstN?worst:0,worstN,months,green:n?Object.values(months).filter(v=>v>0).length:null,
  stop:n&&!noStop?sHi:null,stopLeast:n&&!noStop?sLo:null,target:n&&!noTgt?gHi:null,targetLeast:n&&!noTgt?gLo:null,t};
}
// PROFITABLE by the rule, over what the row shows: money after every fee and at least min_unseen trades
const profitable=(m,D)=>m.trades>=D.min_unseen&&m.profit>0;
function monthKey(s){const d=new Date(s*1000);return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}`}
function monthEnd(key){const [y,m]=key.split("-").map(Number);return new Date(y,m,1).getTime()/1000}
function monthList(D){const out=[],last=monthKey(D.end/1000);let [y,m]=monthKey(D.split/1000).split("-").map(Number);
 for(;;){const key=`${y}-${String(m).padStart(2,"0")}`;out.push(key);if(key>=last)break;m++;if(m>12){m=1;y++}}
 return out}
function monthsIn(months,end_s,days){if(!days)return months.slice();const from=end_s-days*86400;return months.filter(m=>monthEnd(m)>from)}
// the window a "last N days" box means: it starts where the data starts when N is longer than the data
function windowOf(D,days){const end=D.end/1000,split=D.split/1000,all=(end-split)/86400;
 if(!days)return {start:split,span:all,clamped:false,from:null,window_days:all};
 const want=end-days*86400;
 if(want<=split)return {start:split,span:all,clamped:days>all,from:null,window_days:all};
 return {start:want,span:days,clamped:false,from:want,window_days:all}}
// a row's own days in the window: a coin listed inside the unseen days has fewer of them than the window
const daysIn=(r,w)=>Math.max(1/24,Math.min(w.span,r.days));
// the filters a measured row fails, by name (inclusive ceilings and floors; a row with no trade has no number to meet any of them)
function fails(m,f,D){const out=[];
 if(f.pass&&!profitable(m,D))out.push("profitable only");
 if(f.wr!=null&&!(m.win!=null&&m.win>=f.wr))out.push("min win %");
 if(f.ratio!=null&&!(m.ratio!=null&&m.ratio>=f.ratio))out.push("min win ÷ loss size");
 if(f.pr!=null&&!(m.profit!=null&&m.profit>=f.pr))out.push("min profit $");
 if(f.gm!=null&&!(m.green!=null&&m.green>=f.gm))out.push("min months green");
 if(f.dd!=null&&!(m.trades>0&&-m.worst<=f.dd))out.push("max worst dip $");
 if(f.tp!=null&&!(m.target!=null&&m.target<=f.tp))out.push("max TP %");
 if(f.sl!=null&&!(m.stop!=null&&m.stop<=f.sl))out.push("max SL %");
 return out}
function filterNames(f,D){const w={pass:()=>`profitable (money after every fee, ${D.min_unseen}+ trades)`,wr:v=>`win at least ${v}%`,
 ratio:v=>`a win at least ${v}x a loss`,pr:v=>`profit at least ${money(v)}`,gm:v=>`${v} or more months green`,
 dd:v=>`worst dip no worse than −${usd(v)}`,tp:v=>`target at most ${v}% on every trade`,sl:v=>`stop at most ${v}% on every trade`};
 return Object.keys(w).filter(k=>f[k]!=null&&f[k]!==false).map(k=>w[k](f[k]))}
// the counts above the table: judged, profitable, and what luck alone would make profitable (each row's share, added up)
function tally(xs,D){let prof=0,luck=0;for(const x of xs){if(profitable(x.m,D))prof++;luck+=x.r.luck_profitable||0}
 return {rows:xs.length,profitable:prof,luck}}
const levWords=lev=>lev?(lev[0]===lev[1]?`${lev[0]}x`:`${lev[0]}x-${lev[1]}x`):null;
function sortVal(x,c){const m=x.m,r=x.r,t=m.trades;
 const v={profit:m.profit,tp:m.target,sl:m.stop,trades:t||null,perday:t||null,wins:t?m.wins:null,losses:t?m.losses:null,win:m.win,
  avgwin:m.avgWin,avgloss:m.avgLoss,ratio:m.ratio,worst:t?m.worst:null,green:m.green,per:m.per,rmed:r.random_median,
  luck:r.luck_share,lprof:r.luck_profitable,wlday:t?m.wins:null,cost:r.cost_share};
 return c in v?v[c]:String(r[c]??"")}
function sortRows(xs,k,dir){return [...xs].sort((a,b)=>{const p=sortVal(a,k),q=sortVal(b,k);if(p==null&&q==null)return 0;if(p==null)return 1;if(q==null)return -1;
 return (typeof p==="number"&&typeof q==="number"?p-q:String(p).localeCompare(String(q)))*dir})}
const WHY_WORDS={not_reached:"not reached",failed:"failed",unmeasured:"claimed by a machine and not finished",
 left_out:"left out by the machine",refused_records:"record refused at landing",downloads_failed:"on an account whose download failed",
 shares_refused:"on an account that refused its share",machines_refused:"on an account whose machines refused to measure",
 other_records:"measured under another plan or risk",no_walk:"no timeframe measured",not_dispatched:"not sent"};
/*END LOGIC*/
const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const pct=v=>v==null?"":v.toFixed(2)+"%";
const rng=(lo,hi)=>lo==null||hi==null?"":(Math.abs(hi-lo)<1e-9?pct(hi):pct(lo)+" to "+pct(hi));
const num=s=>{const v=parseFloat(s);return Number.isFinite(v)?v:null};
const PAGE=100,LOG_PAGE=100;
let D=null,ROWS=[];
const state={risk:0,f:{},days:null,coin:"",id:"",opened:"",cur:"",log:0,page:0,sort:{k:"profit",dir:-1}};
const idKey=()=>state.id.replace(/^#/,"").toUpperCase();
const COLS=[["id","ID",1],["coin","Coin",1],["kind","Kind",1],["family","Idea",1],["tf","Timeframe",1],["filter","Filter",1],["setting","Setting",1],
 ["verdict","Verdict",1],["profit","PROFIT (total $)"],["target_rule","TP (target rule)",1],["tp","TP % (every trade)"],["stop_rule","SL (stop rule)",1],
 ["sl","SL % (every trade)"],["lev","Leverage",1],["trades","Trades"],["perday","Trades a day"],["wins","W"],["losses","L"],["wlday","W / L a day"],
 ["win","Win %"],["avgwin","Avg win $"],["avgloss","Avg loss $"],["ratio","Win size ÷ loss size"],["worst","Worst losing run"],["green","Months green"],
 ["per","$ a trade"],["rmed","Random median $ (all unseen days)"],["luck","Random runs that made as much (all unseen days)"],
 ["lprof","Random runs profitable by the rule (all unseen days)"],["cost","Typical cost (all unseen days)"]];
function view(){const end=D.end/1000,w=windowOf(D,state.days),k=state.risk/D.risk;
 const months=monthsIn(monthList(D),end,state.days);
 const rows=ROWS.map(r=>({r,m:measure(r,w.from,k)}));
 let shown;const id=idKey(),coin=state.coin.toUpperCase();
 if(id){shown=rows.filter(x=>x.r.id===id)}
 else shown=rows.filter(x=>!fails(x.m,state.f,D).length&&(!coin||x.r.coin.toUpperCase().includes(coin)));
 return {rows,shown,months,w,end,k}}
function cellOf(x,c,w,k,months){const r=x.r,m=x.m,span=daysIn(r,w);const why=`<span class="muted">${esc(r.blank||"no trade in this window")}</span>`;
 switch(c){case"id":return `<span class="id">#${esc(r.id)}</span>`;case"coin":case"kind":case"family":case"tf":case"filter":return esc(r[c]);
  case"setting":return r.setting?esc(r.setting):why;
  case"verdict":{const ok=profitable(m,D);return state.days&&r.setting?`<b class="${ok?"pos":"neg"}">${ok?"PROFITABLE":"not profitable"} in the window</b>`:`<b class="${r.profitable?"pos":"neg"}">${esc(r.verdict)}</b>`}
  case"profit":return m.trades?`<b class="${m.profit>0?"pos":"neg"}">${money(m.profit)}</b>`:why;
  case"target_rule":case"stop_rule":return r[c]?esc(r[c]):why;
  case"tp":return m.target!=null?rng(m.targetLeast,m.target):(m.trades?'<span class="muted">none (trailing stop)</span>':why);
  case"sl":return m.stop!=null?rng(m.stopLeast,m.stop):why;case"lev":return r.lev?levWords(r.lev):why;
  case"trades":return m.trades?m.trades:why;case"perday":return m.trades?(m.trades/span).toFixed(2):why;
  case"wins":return m.trades?m.wins:why;case"losses":return m.trades?m.losses:why;
  case"wlday":return m.trades?`${(m.wins/span).toFixed(2)} / ${(m.losses/span).toFixed(2)}`:why;
  case"win":return m.win!=null?m.win.toFixed(1)+"%":why;case"avgwin":return m.avgWin!=null?money(m.avgWin):(m.trades?"no win":why);
  case"avgloss":return m.avgLoss!=null?money(-m.avgLoss):(m.trades?"no loss":why);
  case"ratio":return m.ratio!=null?m.ratio.toFixed(2)+"x":(m.trades?(m.avgLoss?"no win":"no loss"):why);
  case"worst":return m.trades?(m.worstN?`${money(m.worst)} over ${m.worstN}`:"no losses"):why;
  case"green":return m.trades?`${m.green}/${months.length}`:why;case"per":return m.trades?money(m.per):why;
  case"rmed":return r.random_median!=null?money(r.random_median*k):why;
  case"luck":return r.luck_share!=null?(r.luck_share*100).toFixed(1)+"%":why;
  case"lprof":return r.luck_profitable!=null?(r.luck_profitable*100).toFixed(1)+"%":why;
  case"cost":return esc(r.cost_unseen)}}
const LIMITS={wr:"min win %",ratio:"min win ÷ loss size",pr:"min profit $",gm:"min months green",dd:"max worst dip $",tp:"max TP %",sl:"max SL %"};
function render(){const v=view(),s=state.sort;const sorted=sortRows(v.shown,s.k,s.dir);
 const pages=Math.max(1,Math.ceil(sorted.length/PAGE));state.page=Math.min(Math.max(state.page,0),pages-1);
 const a=state.page*PAGE,page=sorted.slice(a,a+PAGE);
 $("thead").innerHTML="<tr>"+COLS.map(([c,l,left])=>`<th data-k="${c}" class="${left?"l":""}">${esc(l)}${s.k===c?(s.dir>0?" ▲":" ▼"):""}</th>`).join("")
  +v.months.map(m=>`<th>${MON[+m.slice(5)-1]} ${m.slice(0,4)} $</th>`).join("")+"</tr>";
 $("tbody").innerHTML=page.map(x=>`<tr class="row" data-id="${esc(x.r.id)}">`+COLS.map(([c,_l,left])=>`<td class="${left?"l":""}">${cellOf(x,c,v.w,v.k,v.months)}</td>`).join("")
  +v.months.map(m=>{const p=x.m.months[m];return `<td class="${p>0?"pos":p<0?"neg":""}">${p==null?'<span class="muted">no trade</span>':money(p)}</td>`}).join("")+"</tr>").join("");
 $("p-at").textContent=`rows ${sorted.length?a+1:0}-${a+page.length} of ${sorted.length} (page ${state.page+1} of ${pages})`;
 $("p-prev").disabled=!state.page;$("p-next").disabled=state.page>=pages-1;
 const names=filterNames(state.f,D);if(state.coin)names.push(`coin contains "${state.coin}"`);
 const idle=Object.keys(LIMITS).filter(key=>state.f[key]!=null&&v.rows.every(x=>!fails(x.m,{[key]:state.f[key]},D).length))
  .map(key=>`${LIMITS[key]} cuts nothing here: every row already meets it`);
 const noTarget=state.f.tp!=null?v.rows.filter(x=>x.m.trades&&x.m.target==null).length:0;
 const w=v.w,id=idKey(),all=tally(v.rows,D),sh=tally(v.shown,D);
 $("head").innerHTML=`<b>${all.rows.toLocaleString()}</b> coin x idea rows judged on ${D.coins.toLocaleString()} coins. <b>${all.profitable.toLocaleString()}</b> made money after every fee with ${D.min_unseen}+ trades${state.days?" in the window shown":" on the unseen days"}. Luck alone would make about <b>${all.luck.toFixed(1)}</b> of them profitable: each row's share of its ${D.runs} random runs that pass the same rule on all its unseen days, added up${all.luck>0?` - so the real count is ${(all.profitable/all.luck).toFixed(2)}x what luck gives`:""}.`
  +(v.shown.length!==v.rows.length?` Of the ${sh.rows.toLocaleString()} rows shown: ${sh.profitable.toLocaleString()} profitable, luck about ${sh.luck.toFixed(1)}.`:"");
 $("count").innerHTML=`<b>${v.shown.length.toLocaleString()}</b> of ${ROWS.length.toLocaleString()} coin x idea rows`
  +(id?(v.shown.length?` · found by ID (the other filters are off)`:` · no row has #${esc(id)} (the other filters are off)`):"")
  +(names.length&&!id?" · "+esc(names.join(" AND ")):"")
  +` · window ${fmtWhen(w.start*1000)} to ${fmtWhen(D.end)} (${Math.round(w.span)} days)`
  +(state.days?(w.clamped?` · last ${state.days} days is longer than the ${Math.round(w.window_days)} days measured: all unseen days, every row re-added from its trades`:" (every row re-added from its trades that closed in it: no minutes ride in a page, so it is not a new walk; the random-run columns stay over all unseen days)"):"")
  +` · at ${usd(state.risk)} risk a trade`+(state.risk!==D.risk?` (scaled from the ${usd(D.risk)} measured: at another risk some trades would be sized differently or be under one lot)`:"")
  +(noTarget?` · max TP % leaves out ${noTarget} row(s) with a trailing stop, which has no target`:"")+(idle.length?" · "+esc(idle.join("; ")):"");
 drawProv();
 document.querySelectorAll("#thead th").forEach(th=>th.onclick=()=>{const k=th.dataset.k;if(!k)return;state.sort={k,dir:state.sort.k===k?-state.sort.dir:-1};state.page=0;render()});
 document.querySelectorAll("#tbody tr").forEach(tr=>tr.onclick=()=>open(tr.dataset.id))}
function open(id){state.cur=id;state.log=0;drawLog(true)}
function drawLog(show){const v=view(),x=v.rows.find(y=>y.r.id===state.cur);if(!x)return;const r=x.r,m=x.m;
 const pages=Math.max(1,Math.ceil(m.t.length/LOG_PAGE));state.log=Math.min(Math.max(state.log,0),pages-1);
 const a=state.log*LOG_PAGE,b=Math.min(m.t.length,a+LOG_PAGE);let run=0;for(let i=0;i<a;i++)run+=m.t[i][4]/1e4*v.k;
 const span=daysIn(r,v.w);
 $("dlg-body").innerHTML=`<h3><span class="id">#${esc(r.id)}</span> ${esc(r.coin)} ${esc(r.family)} ${esc(r.tf)} ${esc(r.filter)} · ${esc(r.verdict)}</h3>
 <div class="sum"><span>TOTAL PROFIT <b class="total ${m.profit>0?"pos":"neg"}">${m.trades?money(m.profit):"$0.00"}</b></span>
 <span>${m.trades} trades · ${m.wins} won · ${m.losses} lost${m.win!=null?" · "+m.win.toFixed(1)+"%":""}</span>
 <span>a win ${m.avgWin!=null?money(m.avgWin):"-"} · a loss ${m.avgLoss!=null?money(-m.avgLoss):"-"}${m.ratio!=null?` · ${m.ratio.toFixed(2)}x`:""}</span>
 <span>worst losing run <b>${m.worstN?`${money(m.worst)} over ${m.worstN}`:"none"}</b></span></div>
 <p class="note">Setting ${esc(r.setting||"none chosen")}${r.blank?" - "+esc(r.blank):""}. Older days (where the setting was chosen): ${esc(r.older)}. Random runs of this setting on this coin's unseen days (${r.random_runs??0}): median ${money(r.random_median==null?null:r.random_median*v.k)}, ${r.luck_share==null?"-":(r.luck_share*100).toFixed(1)+"%"} made at least as much as the real run, ${r.luck_profitable==null?"-":(r.luck_profitable*100).toFixed(1)+"%"} would be profitable by the rule. Typical cost - entries and exits settled without their own minute's order book: unseen days ${esc(r.cost_unseen)}; older days ${esc(r.cost_older)} (every setting compared). ${m.trades?`${(m.wins/span).toFixed(2)} won and ${(m.losses/span).toFixed(2)} lost a day over the coin's ${span.toFixed(1)} days.`:""}
 Target: ${esc(r.target_rule||"-")}. Stop: ${esc(r.stop_rule||"-")}. Leverage ${r.lev?levWords(r.lev):"-"}, ${r.notional?`${usd(r.notional[0]*v.k)}-${usd(r.notional[1]*v.k)} of coin a trade (margin = the coin bought ÷ its leverage)`:"no trade"}.</p>
 <p class="note">Trades ${m.t.length?a+1:0}-${b} of ${m.t.length} <button id="log-prev"${state.log?"":" disabled"}>Previous ${LOG_PAGE}</button> <button id="log-next"${state.log<pages-1?"":" disabled"}>Next ${LOG_PAGE}</button> (the total above is every trade, not this page)</p>
 <div class="wrap"><table><thead><tr><th class="l">#</th><th class="l">Side</th><th class="l">In</th><th class="l">Out</th><th class="l">Exit</th><th>SL %</th><th>TP %</th><th>Profit</th><th>Running</th></tr></thead><tbody>
 ${m.t.slice(a,b).map((t,j)=>{const p=t[4]/1e4*v.k;run+=p;return `<tr><td class="l">${a+j+1}</td><td class="l">${t[2]>0?"long":"short"}</td><td class="l">${fmtWhen(t[0]*1000)}</td><td class="l">${fmtWhen(t[1]*1000)}</td><td class="l">${esc(D.whys[t[3]])}</td><td>${t[5]>=0?pct(t[5]/1e3):""}</td><td>${t[6]>=0?pct(t[6]/1e3):"none"}</td><td class="${p>0?"pos":"neg"}">${money(p)}</td><td>${money(run)}</td></tr>`}).join("")}
 </tbody></table></div>`;
 $("log-prev").onclick=()=>{state.log--;drawLog(false)};$("log-next").onclick=()=>{state.log++;drawLog(false)};
 if(show)$("dlg").showModal();$("dlg").scrollTop=0}
function drawProv(){const k=state.risk/D.risk,nt=ROWS.flatMap(r=>r.notional||[]);
 $("prov").innerHTML=`<b>${D.tried}</b> combinations tried on each coin (every family x setting x timeframe x filter), judged as up to ${D.groups} ideas a coin on <b>${D.coins.toLocaleString()}</b> of the plan's ${D.plan_coins.toLocaleString()} coins (${D.plan_kind==="all"?"the all-coins plan: every contract in every idea's universe":"the universe plan"}; sent ${D.dispatched??"-"}) on ${esc(D.venue||"the exchange")}. ${esc(D.rule)} Older days ${fmtWhen(D.start)} to ${fmtWhen(D.split)}, unseen days to ${fmtWhen(D.end)}. Every trade risks <b>${usd(state.risk)}</b> if its stop is hit${k!==1?` (scaled from the ${usd(D.risk)} measured)`:""}: ${nt.length?`each buys <b>${usd(Math.min(...nt)*k)}-${usd(Math.max(...nt)*k)}</b> of coin`:"no trade was bought"} at its own leverage (margin = the coin bought ÷ its leverage). Waiting-order entries, the idea's own exit, every fee, each minute's order book where one was recorded, funding. Judged ${fmtWhen(D.judged_at*1000)}; GitHub runs ${esc(Object.entries(D.github_runs).map(([a,n])=>a+" "+n).join(", "))}. ${D.notes.map(esc).join(" ")}`}
function wire(){
 $("dlg-close").onclick=()=>$("dlg").close();$("f-risk").value=D.risk;
 for(const [el,key] of [["f-wr","wr"],["f-ratio","ratio"],["f-pr","pr"],["f-gm","gm"],["f-dd","dd"],["f-tp","tp"],["f-sl","sl"]])$(el).addEventListener("input",e=>{state.f[key]=num(e.target.value);state.page=0;render()});
 $("f-pass").addEventListener("change",e=>{state.f.pass=e.target.value?true:null;state.page=0;render()});
 $("f-risk").addEventListener("input",e=>{const v=num(e.target.value);state.risk=v&&v>0?v:D.risk;render()});
 $("f-days").addEventListener("input",e=>{const v=num(e.target.value);state.days=v&&v>0?Math.floor(v):null;state.page=0;render()});
 $("f-coin").addEventListener("input",e=>{state.coin=e.target.value.trim();state.page=0;render()});
 // find by ID opens that row's log once per new match: only this box opens it, never a later render
 $("f-id").addEventListener("input",e=>{state.id=e.target.value.trim();state.page=0;render();const id=idKey();
  if(id&&ROWS.some(r=>r.id===id)){if(state.opened!==id){state.opened=id;open(id)}}else state.opened=""});
 $("clear").onclick=()=>{state.f={};state.days=null;state.coin="";state.id="";state.opened="";state.page=0;
  for(const el of ["f-wr","f-ratio","f-pr","f-gm","f-dd","f-tp","f-sl","f-days","f-coin","f-id"])$(el).value="";$("f-pass").value="";render()};
 $("p-prev").onclick=()=>{state.page--;render()};$("p-next").onclick=()=>{state.page++;render()};
 $("legend").textContent="Month columns are the calendar months of your own time zone, the same clock as the times shown. SL % and TP % show the tightest to the widest stop and target among the row's trades, and the max SL % / max TP % boxes cut on the widest: every trade's own stop (target) must be at or under the box. Win size ÷ loss size is the average win against the average loss, after every fee.";
 const nj=[];for(const [key,items] of Object.entries(D.not_judged||{}))if(items.length)nj.push(`<details><summary>Not judged - ${esc(WHY_WORDS[key]||key)}: ${items.length}</summary><ul>${items.map(i=>`<li>${esc(i)}</li>`).join("")}</ul></details>`);
 for(const [key,items] of Object.entries(D.accounts||{}))if(items.length)nj.push(`<details><summary>Account - ${esc(key.replace(/_/g," "))}: ${items.length}</summary><ul>${items.map(i=>`<li>${esc(i)}</li>`).join("")}</ul></details>`);
 $("notes").innerHTML=nj.length?nj.join(""):"Every coin of the plan was judged.";
 $("h").textContent=`Backtest v3, coin by coin — ${D.coins.toLocaleString()} coins`;render()}
async function inflate(b64){const bin=Uint8Array.from(atob(b64),c=>c.charCodeAt(0));
 const s=new Blob([bin]).stream().pipeThrough(new DecompressionStream("gzip"));return JSON.parse(await new Response(s).text())}
inflate(Z).then(d=>{D=d;ROWS=rowsOf(D);state.risk=D.risk;wire()}).catch(e=>{$("prov").textContent="The page's data could not be opened: "+e})
</script></body></html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
