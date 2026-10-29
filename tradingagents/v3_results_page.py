"""THE BACKTEST V3 RESULTS PAGE (Part 2b): every judged idea of a published run
as one artifact page with the standard kit (CLAUDE.md "Backtest reporting
requirements").

    python -m tradingagents.v3_results_page <name>   ->  stores.V3.home/pages/<name>.html

Built from the verdict store's kept copy of the run (`v3_verdicts`) and the
records in its folder, never from anything typed: one row per judged group
(family x timeframe x filter, its stable id first, `v3_families.verdict_id`),
each carrying its chosen setting's pooled UNSEEN trades
([coin, entry s, exit s, side, profit x 10,000, exit kind, stop x 100,000,
target x 100,000 or -1]) and every other field - a group that chose nothing
carries no trade and says why in every column (kit F).

Everything a row prints is worked out IN THE PAGE from its trades, so the
risk box rescales every dollar (kit C: the research measured at $5 a trade;
at another risk some trades would be sized differently or be under one lot,
and the page says so), the window box re-adds every row over the trades that
CLOSED in its last N days and drops the month columns outside it (kit G; the
minutes cannot ride in a page, so it is a re-add of the measured trades, never
a new walk - said beside the count), and a click opens the trade-by-trade log
with its TOTAL PROFIT (kit B, D). Max TP % and max SL % read each row's median
target and stop (a trailing stop has no target, so any max TP % leaves it
out, said beside the count).
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

STORE_VERSION = 2        # v3_verdicts.build's shape; another version is refused by name
WHYS = ("TP", "SL", "TRAIL", "MA", "TIME", "END", "RANK")


def payload(store: dict, records: list[dict]) -> dict:
    """The page's data: every judged group with every field (kit F) and its
    chosen setting's pooled unseen trades in the compact encoding above."""
    from tradingagents import v3_families as vf, v3_page as vpg, v3_research as vrs

    if store.get("version") != STORE_VERSION:
        raise ValueError(f"verdict store version {store.get('version')}: this page reads version "
                         f"{STORE_VERSION} (python -m tradingagents.v3_verdicts publish <name>)")
    coins = sorted({r["coin"] for r in records})
    at = {c: i for i, c in enumerate(coins)}
    rows = []
    for v in store["verdicts"]:
        trades = []
        if v.get("setting"):
            key = vf.combo_key(v["family"], v["setting"], v["tf"], v["filter"])
            for rec in records:
                for r in (rec.get("combos", {}).get(key, {}).get("unseen", {}).get("rows") or []):
                    trades.append([at[rec["coin"]], int(r[1]) // 1000, int(r[2]) // 1000,
                                   int(r[3]), int(round(float(r[4]) * 10_000)),
                                   WHYS.index(r[5]),
                                   int(round(float(r[6]) * 100_000)) if len(r) > 6 else -1,
                                   int(round(float(r[7]) * 100_000))
                                   if len(r) > 7 and r[7] is not None else -1])
            trades.sort(key=lambda x: (x[2], x[1], x[0]))
        target, stop = (vrs.exit_words(v["family"], v["setting"], v["tf"]) if v.get("setting")
                        else (None, None))
        row = vpg.check_row(v)
        rnd = v.get("random") or {}
        rows.append({"id": v["id"], "family": v["family"], "tf": v["tf"], "filter": v["filter"],
                     "setting": v.get("setting"), "passed": bool(v.get("passed")),
                     "failed": v.get("failed") or "", "verdict": row["verdict"],
                     "why": row["why"], "blank": row["blank"], "target": target, "stop": stop,
                     "lev": v.get("lev"), "notional": v.get("notional"),
                     "older": {k: [o["trades"], o["per_trade"], o["eligible"]]
                               for k, o in (v.get("older") or {}).items()},
                     "random": [rnd.get("median"), rnd.get("bar"), rnd.get("traded"),
                                rnd.get("runs")],
                     "boot": (v.get("bootstrap") or {}).get("low"),
                     "rand_trades": [row["random_median_trades"], row["real_trades"]],
                     "notes": list(v.get("notes") or []), "t": trades})
    return {"name": store["name"], "venue": store.get("venue") or "", "risk": store["risk_usd"],
            "runs": store["runs"], "tried": store["tried"], "z": store["z"],
            "plan_id": store["plan_id"], "dispatched": store.get("dispatched"),
            "accounts": store.get("accounts") or {}, "start": store["plan_start"],
            "split": store["plan_split"], "end": store["plan_end"],
            "judged_at": store["judged_at"], "coins": coins, "plan_coins": store["plan_coins"],
            "months": store["unseen_months"], "whys": list(WHYS),
            "not_judged": store.get("not_judged") or {}, "github_runs": store["github_runs"],
            "rows": rows}


def build(store: dict, records: list[dict]) -> str:
    return _HTML.replace("/*__DATA__*/null",
                         json.dumps(payload(store, records), separators=(",", ":")))


def newest_kept(name: str) -> Path:
    """The run `name`'s newest kept verdict copy: `<name>-<ms>.json` or `<name>-<ms>-<k>.json`
    (two publishes in one millisecond), newest stamp then highest counter. Another run whose name
    starts with this one's (`pilot-2` beside `pilot`) is never taken for it."""
    from tradingagents import v3_verdicts as vv

    mine = re.compile(rf"^{re.escape(name)}-(\d+)(?:-(\d+))?$")
    kept = [(int(m[1]), int(m[2] or 0), p) for p in vv.history_dir().glob(f"{name}-*.json")
            if (m := mine.match(p.stem))]
    if not kept:
        raise ValueError(f"no verdicts kept for {name}: python -m tradingagents.v3_verdicts "
                         f"publish {name}")
    return max(kept, key=lambda k: k[:2])[2]


def write(name: str) -> Path:
    """The page of the run `name`'s newest kept verdicts, under the v3 store."""
    from tradingagents import stores, v3_research as vrs

    store = json.loads(newest_kept(name).read_text(encoding="utf-8"))
    judged = set(store["coins"])
    records = [r for r in vrs.load_coins(vrs.home(store["folder"])) if r["coin"] in judged]
    out = Path(stores.V3.home) / "pages" / f"{name}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(store, records), encoding="utf-8")
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m tradingagents.v3_results_page")
    p.add_argument("name")
    a = p.parse_args(argv)
    out = write(a.name)
    print(f"{out} ({out.stat().st_size / 1e6:.1f} MB)")
    return 0


_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Backtest v3 Verdicts</title>
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
.prov,.count,.note{color:var(--ink2);font-size:13px;margin:6px 0}.filters{display:flex;flex-wrap:wrap;gap:8px 12px;margin:12px 0}
.filters label{display:flex;flex-direction:column;font-size:12px;color:var(--ink2)}
input,select,button{font:13px var(--sans);padding:4px 6px;border:1px solid var(--rule);border-radius:6px;background:var(--panel);color:var(--ink)}
input[type=number]{width:96px}.wrap{overflow-x:auto;background:var(--panel);border:1px solid var(--rule);border-radius:8px}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{padding:6px 8px;border-bottom:1px solid var(--rule);text-align:right;white-space:nowrap}
th{cursor:pointer;font-size:12px;color:var(--ink2);position:sticky;top:0;background:var(--panel)}
td.l,th.l{text-align:left}.id{font-family:var(--mono)}.pos{color:var(--gain)}.neg{color:var(--loss)}.muted{color:var(--ink3);font-style:italic}
tr.row:hover{background:color-mix(in srgb,var(--accent) 8%,transparent);cursor:pointer}
dialog{max-width:min(1100px,100vw - 32px);width:100%;border:1px solid var(--rule);border-radius:10px;background:var(--panel);color:var(--ink)}
.sum{display:flex;flex-wrap:wrap;gap:6px 18px;margin:8px 0}.total{font-size:18px}
</style></head><body><main>
<h1 id="h">Backtest v3 verdicts</h1>
<p class="prov" id="prov"></p>
<div class="filters">
 <label>Risk a trade $<input id="f-risk" type="number" min="0.1" step="0.5"></label>
 <label>Min win %<input id="f-wr" type="number" min="0" max="100" placeholder="any"></label>
 <label>Min profit $<input id="f-pr" type="number" step="1" placeholder="any"></label>
 <label>Min months green<input id="f-gm" type="number" min="0" step="1" placeholder="any"></label>
 <label>Max worst dip $<input id="f-dd" type="number" min="0" step="1" placeholder="any"></label>
 <label>Max TP %<input id="f-tp" type="number" min="0" step="0.1" placeholder="any"></label>
 <label>Max SL %<input id="f-sl" type="number" min="0" step="0.1" placeholder="any"></label>
 <label>Last N days<input id="f-days" type="number" min="1" step="1" placeholder="all unseen"></label>
 <label>Passed only<select id="f-pass"><option value="">all</option><option value="1">passed</option></select></label>
 <label>Find by ID<input id="f-id" type="text" placeholder="#XXXXXXXX"></label>
 <label>&nbsp;<button id="clear">Clear all filters</button></label>
</div>
<p class="count" id="count"></p>
<div class="wrap"><table><thead id="thead"></thead><tbody id="tbody"></tbody></table></div>
<div class="note" id="notes"></div>
</main>
<dialog id="dlg"><div id="dlg-body"></div><p><button id="dlg-close">Close</button></p></dialog>
<script>
const D = /*__DATA__*/null;
const MON=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
function fmtWhen(ms){const d=new Date(ms);let h=d.getHours();const ap=h<12?"am":"pm";h=h%12||12;
 return `${MON[d.getMonth()]} ${String(d.getDate()).padStart(2,"0")}, ${d.getFullYear()} ${h}:${String(d.getMinutes()).padStart(2,"0")}${ap}`}
/*LOGIC*/
// one row over the trades that CLOSED at or after from_s (null = every unseen trade), dollars x k
function measure(r,from_s,k){
 const t=from_s==null?r.t:r.t.filter(x=>x[2]>=from_s);
 let profit=0,wins=0,run=0,runN=0,worst=0,worstN=0;const months={},stops=[],tgts=[];
 for(const x of t){const p=x[4]/1e4*k;profit+=p;
  if(p>0){wins++;run=0;runN=0}else{run+=p;runN++;if(run<worst){worst=run;worstN=runN}}
  const m=monthKey(x[2]);months[m]=(months[m]||0)+p;if(x[6]>=0)stops.push(x[6]/1e3);if(x[7]>=0)tgts.push(x[7]/1e3)}
 const n=t.length;
 return {trades:n,wins,losses:n-wins,win:n?wins/n*100:null,profit:n?profit:null,per:n?profit/n:null,
  worst:worstN?worst:0,worstN,months,green:Object.values(months).filter(v=>v>0).length,
  stop:median(stops),target:median(tgts),t};
}
function median(xs){if(!xs.length)return null;const s=[...xs].sort((a,b)=>a-b),m=s.length>>1;return s.length%2?s[m]:(s[m-1]+s[m])/2}
function monthKey(s){const d=new Date(s*1000);return `${d.getUTCFullYear()}-${String(d.getUTCMonth()+1).padStart(2,"0")}`}
function monthEnd(key){const [y,m]=key.split("-").map(Number);return Date.UTC(y,m,1)/1000}
// the unseen months a window of the last N days touches (null = every one)
function monthsIn(months,end_s,days){if(!days)return months.slice();const from=end_s-days*86400;return months.filter(m=>monthEnd(m)>from)}
// the filters a measured row fails, by name (inclusive ceilings and floors; a row with no number fails a floor)
function fails(m,f){const out=[];
 if(f.wr!=null&&!(m.win!=null&&m.win>=f.wr))out.push("min win %");
 if(f.pr!=null&&!(m.profit!=null&&m.profit>=f.pr))out.push("min profit $");
 if(f.gm!=null&&!(m.green>=f.gm))out.push("min months green");
 if(f.dd!=null&&!(-m.worst<=f.dd))out.push("max worst dip $");
 if(f.tp!=null&&!(m.target!=null&&m.target<=f.tp))out.push("max TP %");
 if(f.sl!=null&&!(m.stop!=null&&m.stop<=f.sl))out.push("max SL %");
 return out}
// the heading, from the store: a PILOT is a run sent fewer coins than its plan holds
function heading(D){const n=D.coins.length;
 if(D.dispatched!=null&&D.dispatched<D.plan_coins)return `Pilot — ${n} of the plan's ${D.plan_coins} coins, not the proof`;
 if(n<D.plan_coins)return `Full run — ${D.plan_coins-n} of ${D.plan_coins} coins not judged`;
 return `Every idea's verdict — ${n} coins`}
const WHY_WORDS={not_reached:"not reached",failed:"failed",unmeasured:"claimed by a machine and not finished",
 left_out:"left out by the machine",refused_records:"record refused at landing",downloads_failed:"on an account whose download failed",
 shares_refused:"on an account that refused its share",other_records:"measured under another plan or risk",no_walk:"no timeframe measured",
 not_dispatched:"not sent (a pilot)"};
const ACCOUNT_WORDS={downloads_failed:"Download failed",shares_refused:"Share refused",machines_refused:"Machines refused",unreadable_records:"Unreadable record"};
// every coin of the plan not judged, one bucket each, then the accounts that failed; empty buckets print nothing
function notJudged(D){const out=[];
 for(const [key,items] of Object.entries(D.not_judged||{}))if(items.length)out.push({key,label:WHY_WORDS[key]||key.replace(/_/g," "),items,account:false});
 for(const [key,items] of Object.entries(D.accounts||{}))if(items.length)out.push({key,label:ACCOUNT_WORDS[key]||key.replace(/_/g," "),items,account:true});
 return out}
/*END LOGIC*/
const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const money=v=>v==null?"":(v>0?"+":"")+(v<0?"-":"")+"$"+Math.abs(v).toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2});
const usd=v=>"$"+Math.abs(v).toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2});
const pct=v=>v==null?"":v.toFixed(2)+"%";
const num=s=>{const v=parseFloat(s);return Number.isFinite(v)?v:null};
const state={risk:D.risk,f:{},days:null,pass:"",id:"",sort:{k:"profit",dir:-1}};
const COLS=[["id","ID",1],["family","Idea",1],["tf","Timeframe",1],["filter","Filter",1],["setting","Setting",1],
 ["verdict","Verdict",1],["profit","PROFIT (total $)"],["target","TP (target rule)",1],["tp","TP %"],["stop","SL (stop rule)",1],
 ["sl","SL %"],["lev","Leverage",1],["trades","Trades"],["perday","Trades a day"],["wins","W"],["losses","L"],["win","Win %"],
 ["worst","Worst losing run"],["green","Months green"],["per","$ a trade"],["bar","Random bar $ a trade"]];
function view(){const end=D.end/1000,from=state.days?end-state.days*86400:null,k=state.risk/D.risk;
 const months=monthsIn(D.months,end,state.days),span=(state.days||Math.round((D.end-D.split)/86400000));
 const rows=D.rows.map(r=>({r,m:measure(r,from,k)}));
 let shown;const id=state.id.replace(/^#/,"").toUpperCase();
 if(id){shown=rows.filter(x=>x.r.id===id)}else{shown=rows.filter(x=>!fails(x.m,state.f).length&&(!state.pass||x.r.passed))}
 return {rows,shown,months,span,from,end,k}}
function cellOf(x,c,span,k){const r=x.r,m=x.m;const why=`<span class="muted">${esc(r.blank||"no trade in this window")}</span>`;
 switch(c){case"id":return `<span class="id">#${r.id}</span>`;case"family":return r.family;case"tf":return r.tf;case"filter":return r.filter;
  case"setting":return r.setting||why;case"verdict":return `<b class="${r.passed?"pos":"neg"}">${esc(r.verdict)}</b>`;
  case"profit":return m.trades?`<b class="${m.profit>0?"pos":"neg"}">${money(m.profit)}</b>`:why;
  case"target":return r.target?esc(r.target):why;case"stop":return r.stop?esc(r.stop):why;
  case"tp":return m.target!=null?pct(m.target):(m.trades?'<span class="muted">none (trailing stop)</span>':why);
  case"sl":return m.stop!=null?pct(m.stop):why;case"lev":return r.lev?`${r.lev[0]}x-${r.lev[1]}x`:why;
  case"trades":return m.trades;case"perday":return (m.trades/span).toFixed(2);case"wins":return m.trades?m.wins:why;
  case"losses":return m.trades?m.losses:why;case"win":return m.win!=null?m.win.toFixed(1)+"%":why;
  case"worst":return m.trades?(m.worstN?`${money(m.worst)} over ${m.worstN}`:"no losses"):why;
  case"green":return `${m.green}/${x.months.length}`;case"per":return m.trades?money(m.per):why;
  case"bar":return r.random[1]!=null?money(r.random[1]*k):why}}
function sortVal(x,c){const m=x.m,r=x.r;return {profit:m.profit,tp:m.target,sl:m.stop,trades:m.trades,perday:m.trades,wins:m.wins,
 losses:m.losses,win:m.win,worst:m.worst,green:m.green,per:m.per,bar:r.random[1]}[c]??String(r[c]??"")}
function render(){const v=view();v.shown.forEach(x=>x.months=v.months);
 const s=state.sort;v.shown.sort((a,b)=>{const p=sortVal(a,s.k),q=sortVal(b,s.k);if(p==null)return 1;if(q==null)return -1;
  return (typeof p==="number"&&typeof q==="number"?p-q:String(p).localeCompare(String(q)))*s.dir});
 $("thead").innerHTML="<tr>"+COLS.map(([c,l,left])=>`<th data-k="${c}" class="${left?"l":""}">${esc(l)}${s.k===c?(s.dir>0?" ▲":" ▼"):""}</th>`).join("")
  +v.months.map(m=>`<th>${MON[+m.slice(5)-1]} ${m.slice(0,4)} $</th>`).join("")+"</tr>";
 $("tbody").innerHTML=v.shown.map(x=>`<tr class="row" data-id="${x.r.id}">`+COLS.map(([c,_l,left])=>`<td class="${left?"l":""}">${cellOf(x,c,v.span,v.k)}</td>`).join("")
  +v.months.map(m=>{const p=x.m.months[m];return `<td class="${p>0?"pos":p<0?"neg":""}">${p==null?'<span class="muted">no trade</span>':money(p)}</td>`}).join("")+"</tr>").join("");
 const names=Object.entries(state.f).filter(([,val])=>val!=null).map(([key,val])=>({wr:`win ${val}%+`,pr:`profit ${money(val)}+`,gm:`${val}+ months green`,
  dd:`worst dip ${money(val)} or less`,tp:`TP ${val}% or less`,sl:`SL ${val}% or less`}[key]));
 if(state.pass)names.push("passed only");
 const idle=Object.entries(state.f).filter(([,val])=>val!=null).filter(([key])=>v.rows.every(x=>!fails(x.m,{[key]:state.f[key]}).length))
  .map(([key])=>`${{wr:"min win %",pr:"min profit $",gm:"min months green",dd:"max worst dip $",tp:"max TP %",sl:"max SL %"}[key]} cuts nothing here: every row already meets it`);
 const noTarget=state.f.tp!=null?v.rows.filter(x=>x.m.trades&&x.m.target==null).length:0;
 $("count").innerHTML=`<b>${v.shown.length}</b> of ${D.rows.length} judged groups`+(state.id?` · found by ID (the other filters are off)`:"")
  +(names.length&&!state.id?" · "+esc(names.join(" AND ")):"")
  +` · window ${fmtWhen((v.from??D.split/1000)*1000)} to ${fmtWhen(D.end)}`+(state.days?" (every row re-added from its trades that closed in it)":"")
  +` · at ${usd(state.risk)} risk a trade`+(state.risk!==D.risk?` (scaled from the ${usd(D.risk)} measured: at another risk some trades would be sized differently or be under one lot)`:"")
  +(noTarget?` · max TP % leaves out ${noTarget} row(s) whose trailing stop has no target`:"")+(idle.length?" · "+esc(idle.join("; ")):"");
 document.querySelectorAll("#thead th").forEach(th=>th.onclick=()=>{const k=th.dataset.k;if(!k)return;state.sort={k,dir:state.sort.k===k?-state.sort.dir:-1};render()});
 document.querySelectorAll("#tbody tr").forEach(tr=>tr.onclick=()=>open(tr.dataset.id));
 if(state.id&&v.shown.length===1)open(v.shown[0].r.id)}
function open(id){const v=view(),x=v.rows.find(y=>y.r.id===id);if(!x)return;const r=x.r,m=x.m;let run=0;
 const older=Object.entries(r.older).map(([s,[n,p,ok]])=>`${esc(s)}: ${n} older trades, ${p==null?"no trade":money(p*v.k)+" a trade"}${ok?"":" (too few to choose)"}`).join(" · ");
 $("dlg-body").innerHTML=`<h3><span class="id">#${r.id}</span> ${esc(r.family)} ${r.tf} ${esc(r.filter)} · ${esc(r.verdict)}</h3>
 <div class="sum"><span>TOTAL PROFIT <b class="total ${m.profit>0?"pos":"neg"}">${m.trades?money(m.profit):"$0.00"}</b></span>
 <span>${m.trades} trades · ${m.wins} won · ${m.losses} lost${m.win!=null?" · "+m.win.toFixed(1)+"%":""}</span>
 <span>worst losing run <b>${m.worstN?`${money(m.worst)} over ${m.worstN}`:"none"}</b></span></div>
 <p class="note">Setting ${esc(r.setting||"none chosen")} - ${esc(r.why)}. Older days: ${older||"no trades"}. Random runs: median ${money(r.random[0]==null?null:r.random[0]*v.k)}, bar ${money(r.random[1]==null?null:r.random[1]*v.k)} a trade (${r.random[2]??0} of ${r.random[3]??0} traded; their median ${r.rand_trades[0]??"-"} trades against the real run's ${r.rand_trades[1]??"-"}). Bootstrap low ${money(r.boot==null?null:r.boot*v.k)} a trade.
 Target: ${esc(r.target||"-")}. Stop: ${esc(r.stop||"-")}. Leverage ${r.lev?`${r.lev[0]}x-${r.lev[1]}x`:"-"}, ${r.notional?`${money(r.notional[0]*v.k)}-${money(r.notional[1]*v.k)} of coin a trade (margin = the coin bought ÷ its leverage)`:"no trade"}. ${r.notes.map(esc).join(" ")}</p>
 <div class="wrap"><table><thead><tr><th class="l">#</th><th class="l">Coin</th><th class="l">Side</th><th class="l">In</th><th class="l">Out</th><th class="l">Exit</th><th>SL %</th><th>TP %</th><th>Profit</th><th>Running</th></tr></thead><tbody>
 ${m.t.map((t,i)=>{const p=t[4]/1e4*v.k;run+=p;return `<tr><td class="l">${i+1}</td><td class="l">${esc(D.coins[t[0]])}</td><td class="l">${t[3]>0?"long":"short"}</td><td class="l">${fmtWhen(t[1]*1000)}</td><td class="l">${fmtWhen(t[2]*1000)}</td><td class="l">${D.whys[t[5]]}</td><td>${t[6]>=0?pct(t[6]/1e3):""}</td><td>${t[7]>=0?pct(t[7]/1e3):"none"}</td><td class="${p>0?"pos":"neg"}">${money(p)}</td><td>${money(run)}</td></tr>`}).join("")}
 </tbody></table></div>`;$("dlg").showModal();$("dlg").scrollTop=0}
$("dlg-close").onclick=()=>$("dlg").close();
$("f-risk").value=D.risk;
for(const [el,key] of [["f-wr","wr"],["f-pr","pr"],["f-gm","gm"],["f-dd","dd"],["f-tp","tp"],["f-sl","sl"]])$(el).addEventListener("input",e=>{state.f[key]=num(e.target.value);render()});
$("f-risk").addEventListener("input",e=>{const v=num(e.target.value);state.risk=v&&v>0?v:D.risk;render()});
$("f-days").addEventListener("input",e=>{const v=num(e.target.value);state.days=v&&v>0?Math.floor(v):null;render()});
$("f-pass").addEventListener("change",e=>{state.pass=e.target.value;render()});
$("f-id").addEventListener("input",e=>{state.id=e.target.value.trim();render()});
$("clear").onclick=()=>{state.f={};state.days=null;state.pass="";state.id="";for(const el of ["f-wr","f-pr","f-gm","f-dd","f-tp","f-sl","f-days","f-id"])$(el).value="";$("f-pass").value="";render()};
const NOTIONAL=D.rows.flatMap(r=>r.notional||[]);
$("h").textContent=`Backtest v3: ${heading(D)}`;
$("prov").innerHTML=`<b>${D.tried}</b> combinations tried (every family x setting x timeframe x filter), judged as ${D.rows.length} groups on <b>${D.coins.length}</b> of the plan's ${D.plan_coins} coins (${D.dispatched==null?"sent: not recorded":"sent "+D.dispatched}) on ${esc(D.venue||"the exchange")}: each group's setting chosen on the older days ${fmtWhen(D.start)} to ${fmtWhen(D.split)}, judged on the unseen days to ${fmtWhen(D.end)} against ${D.runs} random runs (z ${D.z.toFixed(3)}). Every trade risks <b>${usd(D.risk)}</b> if its stop is hit: ${NOTIONAL.length?`each buys <b>${usd(Math.min(...NOTIONAL))}-${usd(Math.max(...NOTIONAL))}</b> of coin`:"no trade was bought"} at its own leverage (margin = the coin bought ÷ its leverage). Waiting-order entries, the idea's own exit, every fee, each minute's order book where one was recorded, funding. Judged ${fmtWhen(D.judged_at*1000)}; GitHub runs ${esc(Object.entries(D.github_runs).map(([a,n])=>a+" "+n).join(", "))}.`;
const NJ=notJudged(D);
$("notes").innerHTML=NJ.length?NJ.map(x=>`<details><summary>${x.account?"Account":"Not judged"} - ${esc(x.label)}: ${x.items.length}</summary><ul>${x.items.map(i=>`<li>${esc(i)}</li>`).join("")}</ul></details>`).join(""):"Every coin of the plan was judged.";
render();
</script></body></html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
