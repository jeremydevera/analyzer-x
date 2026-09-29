"""The criteria-research page, built from watcher_research's result JSON.

    python -m tradingagents.research_page <name>  ->  ~/.tradingagents/replay/research-<name>.html

Every rule set is a row: its dials, what it made on Jul-Aug (where it was
chosen) and on September (which it never saw). Everything on the page is
computed in the page from the embedded per-day results, so the base-margin box
re-prices every figure (kit C). Dates come from the same JS copy of the project
format as the replay page (tests/test_research_page.py pins it to fmt_when).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

OUT_DIR = Path(os.path.expanduser("~/.tradingagents")) / "replay"
DIALS = ("on_winrate", "off_winrate", "min_trades", "tp_rule", "window_days",
         "rank", "max_per_coin", "max_new_per_day", "cooldown_days",
         "off_streak_live")
PARTS = ("profit", "closed", "wins", "losses", "winrate", "slots", "open",
         "worst_day", "green_days", "days_n", "max_dd", "worst_run",
         "worst_run_n", "max_open")


def payload(res: dict) -> dict:
    """Compact and complete: every rule set carries every field (kit F)."""
    rows = []
    for r in res["rows"]:
        rows.append({"id": r["id"], "c": [r["cfg"][k] for k in DIALS],
                     "tr": [r["train"][k] for k in PARTS], "trd": r["train"]["days"],
                     "te": [r["test"][k] for k in PARTS], "ted": r["test"]["days"]})
    t = res["totals"]
    return {"rows": rows, "dials": list(DIALS), "parts": list(PARTS),
            "train": res["train"], "test": res["test"], "end": res["end_ms"],
            "current": res["current_id"], "best_train": res["best_train_id"],
            "combos": res["combos"], "tested": t["tested"],
            "coins": t.get("coins_by_groups") or {}, "board": t["coins_board"],
            "groups": t.get("groups") or [], "base": 5.0, "lev": 20}


def build(res: dict) -> str:
    return _HTML.replace("/*__DATA__*/null",
                         json.dumps(payload(res), separators=(",", ":")))


def main(argv=None) -> int:
    name = (argv or sys.argv[1:])[0]
    res = json.loads((OUT_DIR / f"research-{name}.json").read_text(encoding="utf-8"))
    path = OUT_DIR / f"research-{name}.html"
    path.write_text(build(res), encoding="utf-8")
    print(path)
    return 0


_HTML = r"""<title>Watcher Rules Research</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap">
<style>
:root{color-scheme:light;
 --bg:#f6f7f5;--panel:#ffffff;--ink:#15191a;--ink2:#4b5355;--ink3:#7a8386;
 --rule:#dde2df;--accent:#0f6b62;--accent-soft:#e3f0ee;
 --gain:#2a78d6;--loss:#e34948;--s1:#2a78d6;--s2:#eb6834;--warn:#9a6300;--warn-soft:#fbf1dc;
 --sans:"Instrument Sans",system-ui,-apple-system,"Segoe UI",sans-serif;
 --mono:"JetBrains Mono",ui-monospace,Consolas,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;
 --bg:#111514;--panel:#181d1c;--ink:#eef2f0;--ink2:#b3bcb9;--ink3:#86908d;
 --rule:#2b3331;--accent:#4fb3a7;--accent-soft:#1c2f2c;
 --gain:#3987e5;--loss:#e66767;--s1:#3987e5;--s2:#d95926;--warn:#e0a53a;--warn-soft:#2e2615}}
:root[data-theme="dark"]{color-scheme:dark;
 --bg:#111514;--panel:#181d1c;--ink:#eef2f0;--ink2:#b3bcb9;--ink3:#86908d;
 --rule:#2b3331;--accent:#4fb3a7;--accent-soft:#1c2f2c;
 --gain:#3987e5;--loss:#e66767;--s1:#3987e5;--s2:#d95926;--warn:#e0a53a;--warn-soft:#2e2615}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);font:15px/1.5 var(--sans);margin:0;padding-inline:16px;padding-block:20px 48px}
main{max-width:1240px;margin:0 auto;display:flex;flex-direction:column;gap:22px}
h1{font-size:28px;line-height:1.15;margin:0;text-wrap:balance;letter-spacing:-.01em}
h2{font-size:17px;margin:0;text-wrap:balance}
.eyebrow{font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--accent)}
.lede{max-width:75ch;color:var(--ink2);margin:6px 0 0}
.panel{background:var(--panel);border:1px solid var(--rule);border-radius:10px;padding:16px}
.prov,.note{font-size:13px;color:var(--ink2);max-width:100ch}
.cmp{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}
.card{background:var(--panel);border:1px solid var(--rule);border-radius:10px;padding:14px;display:flex;flex-direction:column;gap:6px}
.card.best{border-color:var(--accent)}
.card h3{margin:0;font-size:14px;color:var(--ink2);font-weight:600}
.card .big{font:600 26px/1.1 var(--mono)}
.card .sub{font-size:13px;color:var(--ink2)}
.card .rules{font-size:12.5px;color:var(--ink2);display:flex;flex-wrap:wrap;gap:4px 10px}
.card .rules b{color:var(--ink)}
.pos{color:var(--gain)}.neg{color:var(--loss)}
.chart{position:relative}.chart svg{width:100%;height:240px;display:block;overflow:visible}
.legend{display:flex;gap:14px;font-size:12px;color:var(--ink2)}.legend i{display:inline-block;width:14px;height:3px;border-radius:2px;vertical-align:middle;margin-right:5px}
.tip{position:absolute;pointer-events:none;background:var(--panel);border:1px solid var(--rule);border-radius:8px;padding:6px 9px;font-size:12px;box-shadow:0 4px 14px rgba(0,0,0,.12);white-space:nowrap;z-index:5}
.filters{display:flex;flex-wrap:wrap;gap:10px;align-items:flex-end}
.filters label{display:flex;flex-direction:column;gap:3px;font-size:12px;color:var(--ink2)}
.filters input,.filters select{width:118px;padding:6px 8px;border:1px solid var(--rule);border-radius:7px;background:var(--bg);color:var(--ink);font:13px var(--mono)}
.btn{padding:7px 12px;border:1px solid var(--rule);border-radius:7px;background:var(--panel);color:var(--ink);font:500 13px var(--sans);cursor:pointer}
.btn:hover{border-color:var(--accent)}:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.count{font-size:13px;color:var(--ink2)}.count b{color:var(--ink)}
.scroll{overflow-x:auto;border:1px solid var(--rule);border-radius:10px;background:var(--panel);max-height:640px}
table{border-collapse:collapse;width:100%;font-size:12.5px}
th,td{padding:6px 9px;text-align:right;white-space:nowrap;border-bottom:1px solid var(--rule)}
th{position:sticky;top:0;background:var(--panel);font-weight:600;color:var(--ink2);font-size:11.5px;cursor:pointer;user-select:none;z-index:1}
th.grp{cursor:default;text-align:center;border-bottom:none;color:var(--ink3);font-size:11px;letter-spacing:.06em;text-transform:uppercase}
th.l,td.l{text-align:left}
th[aria-sort="ascending"]::after{content:" ▲";color:var(--accent)}th[aria-sort="descending"]::after{content:" ▼";color:var(--accent)}
td{font-family:var(--mono);font-variant-numeric:tabular-nums}
tbody tr:hover{background:var(--accent-soft)}tr.click{cursor:pointer}
tr.mine td:first-child{box-shadow:inset 3px 0 var(--s2)}tr.top td:first-child{box-shadow:inset 3px 0 var(--accent)}
.id{color:var(--accent)}.muted{color:var(--ink3)}
.tag{font:600 10.5px var(--sans);border-radius:999px;padding:1px 7px;margin-left:6px;vertical-align:1px}
.tag.mine{background:var(--warn-soft);color:var(--warn)}.tag.top{background:var(--accent-soft);color:var(--accent)}
dialog{border:1px solid var(--rule);border-radius:12px;background:var(--panel);color:var(--ink);padding:18px;width:min(900px,calc(100vw - 32px));max-height:86vh}
dialog::backdrop{background:rgba(0,0,0,.35)}
.sum{display:flex;flex-wrap:wrap;gap:14px;font-size:13px;color:var(--ink2)}.sum b{color:var(--ink);font-family:var(--mono)}
.total{font:600 15px var(--mono)}
@media (max-width:560px){h1{font-size:23px}.card .big{font-size:22px}}
</style>
<main>
 <header>
  <div class="eyebrow">Strategy watcher · rules research</div>
  <h1 id="verdict">Which switch-on and switch-off rules make the most</h1>
  <p class="lede" id="lede"></p>
 </header>
 <section class="cmp" id="cmp"></section>
 <section class="panel chart" id="c-sep"><h2>September, day by day</h2>
  <div class="legend" id="legend"></div>
  <svg role="img" aria-label="Running total in September for the chosen rules and yours"></svg></section>
 <p class="prov" id="prov"></p>
 <section class="panel filters" aria-label="Filters">
  <label>Base margin $<input id="f-base" type="number" min="0.5" step="0.5" value="5"></label>
  <label>Min Sep profit $<input id="f-te" type="number" step="1" placeholder="any"></label>
  <label>Min Jul–Aug profit $<input id="f-tr" type="number" step="1" placeholder="any"></label>
  <label>Min Sep win %<input id="f-wr" type="number" min="0" max="100" placeholder="any"></label>
  <label>Max Sep worst dip $<input id="f-dd" type="number" min="0" step="1" placeholder="any"></label>
  <label>Switch on at %<select id="f-on"><option value="">any</option></select></label>
  <label>TP<select id="f-tp"><option value="">any</option><option value=">">wider than SL</option><option value=">=">at least SL</option></select></label>
  <label>Days judged<select id="f-win"><option value="">any</option></select></label>
  <label>Find rule id<input id="f-id" type="text" placeholder="#50B27C00"></label>
  <button class="btn" id="clear" type="button">Clear all</button>
 </section>
 <section style="display:flex;flex-direction:column;gap:10px">
  <h2>Every rule set tried</h2>
  <div class="count" id="count"></div>
  <div class="scroll"><table id="t"><thead></thead><tbody></tbody></table></div>
  <div><button class="btn" id="more" type="button">Show 200 more</button></div>
 </section>
 <p class="note" id="notes"></p>
</main>
<dialog id="dlg" aria-labelledby="dlg-h"><div id="dlg-body" style="display:flex;flex-direction:column;gap:10px"></div><p><button class="btn" id="dlg-close" type="button">Close</button></p></dialog>
<script>
const D = /*__DATA__*/null;
const MON=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
function fmtWhen(ms){const d=new Date(ms);let h=d.getHours();const ap=h<12?"am":"pm";h=h%12||12;
 return `${MON[d.getMonth()]} ${String(d.getDate()).padStart(2,"0")}, ${d.getFullYear()} ${h}:${String(d.getMinutes()).padStart(2,"0")}${ap}`}
function dayLabel(ms){const d=new Date(ms);return `${MON[d.getMonth()]} ${String(d.getDate()).padStart(2,"0")}, ${d.getFullYear()}`}
const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const money=(v,sign=true)=>(sign&&v>0?"+":"")+(v<0?"-":"")+"$"+Math.abs(v).toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2});
const P=Object.fromEntries(D.parts.map((p,i)=>[p,i])),C=Object.fromEntries(D.dials.map((d,i)=>[d,i]));
const state={base:5,te:null,tr:null,wr:null,dd:null,on:"",tp:"",win:"",id:"",sort:{k:"te_profit",dir:-1},shown:200};
const k=()=>state.base/D.base;
const RANK={winrate:"win rate",profit:"profit",trades:"trades"};
function rulesText(r){const c=r.c;return [`switch on at <b>${c[C.on_winrate]}%+</b>`,`off under <b>${c[C.off_winrate]}%</b>`,`<b>${c[C.min_trades]}+</b> trades`,`TP <b>${c[C.tp_rule]===">"?"wider than":"at least"}</b> SL`,`judged on <b>${c[C.window_days]}</b> days`,`best <b>${RANK[c[C.rank]]}</b> first`,`<b>${c[C.max_per_coin]}</b> per coin`,`<b>${c[C.max_new_per_day]}</b> new a day`,`<b>${c[C.cooldown_days]}</b>-day wait`,c[C.off_streak_live]?`off after <b>${c[C.off_streak_live]}</b> practice losses in a row`:`practice losses never switch off`].map(t=>`<span>${t}</span>`).join("")}
function val(r,key){const [part,f]=key.split("_",2).length>1&&(key.startsWith("te_")||key.startsWith("tr_"))?[key.slice(0,2),key.slice(3)]:[null,key];
 if(part){const v=r[part][P[f]];return ["profit","worst_day","max_dd","worst_run"].includes(f)?v*k():v}
 if(key==="id")return r.id;return r.c[C[key]]}
const byId=Object.fromEntries(D.rows.map(r=>[r.id,r]));
function filtered(){const want=state.id.replace(/^#+/,"").trim().toUpperCase();
 if(want)return {rows:D.rows.filter(r=>r.id===want),names:[`rule #${want} (overrides the other filters)`],byId:true};
 const names=[];let out=D.rows;const f=(on,l,p)=>{if(on){names.push(l);out=out.filter(p)}};
 f(state.te!=null,`September profit ≥ ${money(state.te,false)}`,r=>r.te[P.profit]*k()>=state.te);
 f(state.tr!=null,`Jul–Aug profit ≥ ${money(state.tr,false)}`,r=>r.tr[P.profit]*k()>=state.tr);
 f(state.wr!=null,`September win ≥ ${state.wr}%`,r=>r.te[P.winrate]>=state.wr);
 f(state.dd!=null,`September worst dip ≤ ${money(state.dd,false)}`,r=>r.te[P.max_dd]*k()<=state.dd);
 f(!!state.on,`switch on at ${state.on}%`,r=>String(r.c[C.on_winrate])===state.on);
 f(!!state.tp,`TP ${state.tp===">"?"wider than":"at least"} SL`,r=>r.c[C.tp_rule]===state.tp);
 f(!!state.win,`judged on ${state.win} days`,r=>String(r.c[C.window_days])===state.win);
 return {rows:out,names,byId:false}}

const COLS=[["id","rule",1],["on_winrate","on %"],["off_winrate","off %"],["min_trades","trades ≥"],["tp_rule","TP vs SL",1],["window_days","days"],["rank","first",1],["max_per_coin","per coin"],["max_new_per_day","new/day"],["cooldown_days","wait"],["off_streak_live","loss stop"],
 ["tr_profit","PROFIT $"],["tr_closed","trades"],["tr_wins","W"],["tr_losses","L"],["tr_winrate","win %"],["tr_worst_run","worst run"],
 ["te_profit","PROFIT $"],["te_closed","trades"],["te_wins","W"],["te_losses","L"],["te_winrate","win %"],["te_worst_day","worst day"],["te_max_dd","worst dip"],["te_worst_run","worst run"],["te_slots","switched on"],["te_max_open","open at once"]];
function cell(r,key){const v=val(r,key);
 if(key==="id")return `<td class="l id">#${r.id}${r.id===D.current?'<span class="tag mine">yours</span>':""}${r.id===D.best_train?'<span class="tag top">picked</span>':""}</td>`;
 if(key==="tp_rule")return `<td class="l">${v===">"?"wider":"≥"}</td>`;if(key==="rank")return `<td class="l">${RANK[v]}</td>`;
 if(key==="off_streak_live")return `<td>${v||"—"}</td>`;
 if(key.endsWith("_profit")||key.endsWith("worst_day")||key.endsWith("max_dd"))return `<td class="${key.endsWith("max_dd")?(v>0?"neg":""):v>0?"pos":v<0?"neg":""}">${key.endsWith("max_dd")?(v?money(-v):"—"):money(v)}</td>`;
 if(key.endsWith("worst_run")){const part=key.slice(0,2);const n=r[part][P.worst_run_n];return `<td class="${v<0?"neg":""}">${n?`${money(v)} (${n})`:"—"}</td>`}
 if(key==="te_winrate"||key==="tr_winrate")return `<td>${v.toFixed(1)}%</td>`;return `<td>${v}</td>`}
function render(){const F=filtered();const rows=[...F.rows].sort((a,b)=>{const x=val(a,state.sort.k),y=val(b,state.sort.k);return (x>y?1:x<y?-1:0)*state.sort.dir});
 const th=$("t").querySelector("thead");
 th.innerHTML=`<tr><th class="grp" colspan="11">the rules</th><th class="grp" colspan="6">Jul 01 – Aug 31 (where they were tuned)</th><th class="grp" colspan="10">September (never seen while tuning)</th></tr><tr>`+COLS.map(([key,l,left])=>`<th class="${left?"l":""}" data-k="${key}" aria-sort="${state.sort.k===key?(state.sort.dir>0?"ascending":"descending"):"none"}">${l}</th>`).join("")+"</tr>";
 th.querySelectorAll("th[data-k]").forEach(h=>h.onclick=()=>{const key=h.dataset.k;state.sort=state.sort.k===key?{k:key,dir:-state.sort.dir}:{k:key,dir:key==="id"?1:-1};render()});
 $("t").querySelector("tbody").innerHTML=rows.slice(0,state.shown).map(r=>`<tr class="click ${r.id===D.current?"mine":""} ${r.id===D.best_train?"top":""}" data-id="${r.id}" tabindex="0">${COLS.map(([key])=>cell(r,key)).join("")}</tr>`).join("");
 $("t").querySelectorAll("tr.click").forEach(tr=>{const go=()=>openRule(byId[tr.dataset.id]);tr.onclick=go;tr.onkeydown=e=>{if(e.key==="Enter")go()}});
 $("more").hidden=rows.length<=state.shown;
 $("count").innerHTML=`<b>${rows.length.toLocaleString()}</b> of ${D.rows.length.toLocaleString()} rule sets${F.names.length?" · "+esc(F.names.join(" AND ")):""} · showing ${Math.min(rows.length,state.shown).toLocaleString()} · at <b>${money(state.base,false)}</b> × ${D.lev}x = <b>${money(state.base*D.lev,false)}</b> a trade`;
 if(F.byId&&rows.length===1&&opened!==rows[0].id){opened=rows[0].id;openRule(rows[0])}if(!F.byId)opened="";
 drawTop();}
let opened="";

function drawTop(){const best=byId[D.best_train],mine=byId[D.current];
 const hind=D.rows.reduce((m,r)=>r.te[P.profit]>m.te[P.profit]?r:m,D.rows[0]);
 const up=best.te[P.profit]-mine.te[P.profit];
 $("verdict").textContent=up>0?`Better rules would have made ${money(best.te[P.profit]*k(),false)} in September, against ${money(mine.te[P.profit]*k(),false)} with yours`:`Your rules held up: ${money(mine.te[P.profit]*k(),false)} in September, the tuned ones ${money(best.te[P.profit]*k(),false)}`;
 $("lede").textContent=`${D.rows.length.toLocaleString()} rule sets were replayed on July and August and the one that made the most there was picked. The September figures are the fair test: that month played no part in picking it.`;
 const card=(r,title,cls,sub)=>`<div class="card ${cls}"><h3>${title} · <span class="id">#${r.id}</span></h3><div class="big ${r.te[P.profit]>=0?"pos":"neg"}">${money(r.te[P.profit]*k())}</div><div class="sub">in September · ${r.te[P.closed]} trades, ${r.te[P.wins]} won, ${r.te[P.losses]} lost · worst day ${money(r.te[P.worst_day]*k())}</div><div class="sub">up to <b>${r.te[P.max_open]}</b> trades open at once — <b>${money(r.te[P.max_open]*state.base,false)}</b> of margin tied up at ${money(state.base,false)} each</div><div class="sub">Jul–Aug: ${money(r.tr[P.profit]*k())} over ${r.tr[P.closed]} trades${sub?` · ${sub}`:""}</div><div class="rules">${rulesText(r)}</div></div>`;
 $("cmp").innerHTML=card(best,"Picked on Jul–Aug","best","")+card(mine,"Your rules","","")+card(hind,"Best on September (hindsight)","","picked by looking at September, so not a fair test");
 drawSep(best,mine)}

function drawSep(a,b){const box=$("c-sep"),svg=box.querySelector("svg");const W=Math.max(300,svg.getBoundingClientRect().width),H=240,L=62,R=16,T=12,B=28;svg.setAttribute("viewBox",`0 0 ${W} ${H}`);
 const run=r=>{let t=0;return r.ted.map(p=>t+=p*k())};const A=run(a),Bv=run(b);const n=Math.max(A.length,Bv.length);
 const all=[0,...A,...Bv];const lo=Math.min(...all),hi=Math.max(...all);const span=Math.max(1e-9,hi-lo),s0=span/4,p=Math.pow(10,Math.floor(Math.log10(s0)));const step=[1,2,2.5,5,10].map(m=>m*p).find(s=>s>=s0);
 const ticks=[];for(let v=Math.floor(lo/step)*step;v<=Math.ceil(hi/step-1e-9)*step+1e-9;v+=step)ticks.push(+v.toFixed(6));const tl=ticks[0],th=ticks[ticks.length-1];
 const y=v=>T+(th-v)/(th-tl||1)*(H-T-B),x=i=>L+(W-L-R)*(n>1?i/(n-1):.5);
 let g="";for(const v of ticks){g+=`<line x1="${L}" x2="${W-R}" y1="${y(v)}" y2="${y(v)}" stroke="var(--rule)" stroke-width="${v===0?1.5:1}"/><text x="${L-8}" y="${y(v)+4}" text-anchor="end" font-size="11" fill="var(--ink3)" font-family="var(--mono)">${money(v)}</text>`}
 const start=D.test[0];for(let i=0;i<n;i+=Math.ceil(n/7)){const d=new Date(start+i*86400000);g+=`<text x="${x(i)}" y="${H-8}" text-anchor="middle" font-size="11" fill="var(--ink3)">${MON[d.getMonth()]} ${d.getDate()}</text>`}
 const line=(v,c)=>{const pts=v.map((t,i)=>`${x(i)},${y(t)}`).join(" ");const i=v.length-1;return `<polyline points="${pts}" fill="none" stroke="${c}" stroke-width="2" stroke-linejoin="round"/><circle cx="${x(i)}" cy="${y(v[i])}" r="4" fill="${c}" stroke="var(--panel)" stroke-width="2"/><text x="${x(i)-6}" y="${y(v[i])-9}" text-anchor="end" font-size="12" font-family="var(--mono)" fill="var(--ink)">${money(v[i])}</text>`};
 g+=line(Bv,"var(--s2)")+line(A,"var(--s1)");
 g+=`<line class="cross" x1="0" x2="0" y1="${T}" y2="${H-B}" stroke="var(--ink3)" stroke-dasharray="3 3" visibility="hidden"/><rect class="hit" x="${L}" y="${T}" width="${W-L-R}" height="${H-T-B}" fill="transparent"/>`;
 svg.innerHTML=g;$("legend").innerHTML=`<span><i style="background:var(--s1)"></i>picked on Jul–Aug #${a.id}</span><span><i style="background:var(--s2)"></i>your rules #${b.id}</span>`;
 const hit=svg.querySelector(".hit"),cross=svg.querySelector(".cross");
 hit.onmousemove=ev=>{const r=svg.getBoundingClientRect();const px=(ev.clientX-r.left)*(W/r.width);const i=Math.max(0,Math.min(n-1,Math.round((px-L)/((W-L-R)/Math.max(1,n-1)))));
  cross.setAttribute("x1",x(i));cross.setAttribute("x2",x(i));cross.setAttribute("visibility","visible");let t=box.querySelector(".tip");if(!t){t=document.createElement("div");t.className="tip";box.appendChild(t)}
  t.hidden=false;t.innerHTML=`<b>${dayLabel(start+i*86400000)}</b><br>picked: ${money(A[i]??0)} (${money((a.ted[i]||0)*k())} that day)<br>yours: ${money(Bv[i]??0)} (${money((b.ted[i]||0)*k())} that day)`;const b2=box.getBoundingClientRect();t.style.left=Math.min(b2.width-t.offsetWidth-4,Math.max(4,ev.clientX-b2.left-t.offsetWidth/2))+"px";t.style.top=Math.max(0,ev.clientY-b2.top-70)+"px"};
 hit.onmouseleave=()=>{cross.setAttribute("visibility","hidden");const t=box.querySelector(".tip");if(t)t.hidden=true}}

function openRule(r){if(!r)return;const part=(key,days,from)=>{let t=0;return days.map((p,i)=>{t+=p*k();return `<tr><td class="l">${dayLabel(from+i*86400000)}</td><td class="${p>0?"pos":p<0?"neg":""}">${money(p*k())}</td><td>${money(t)}</td></tr>`}).join("")};
 const sum=(v,lbl)=>`<div class="sum"><span>${lbl} TOTAL PROFIT <b class="total ${v[P.profit]>=0?"pos":"neg"}">${money(v[P.profit]*k())}</b></span><span>${v[P.closed]} trades · ${v[P.wins]} won · ${v[P.losses]} lost · ${v[P.winrate].toFixed(1)}%</span><span>worst losing run <b>${v[P.worst_run_n]?`${money(v[P.worst_run]*k())} over ${v[P.worst_run_n]}`:"none"}</b></span><span>${v[P.slots]} strategies switched on</span><span>up to <b>${v[P.max_open]}</b> trades open at once (${money(v[P.max_open]*state.base,false)} of margin)</span></div>`;
 $("dlg-body").innerHTML=`<h3 id="dlg-h" style="margin:0"><span class="id">#${r.id}</span>${r.id===D.current?" · your rules":""}${r.id===D.best_train?" · picked on Jul–Aug":""} · ${D.lev}x · ${money(state.base,false)} margin (${money(state.base*D.lev,false)} a trade)</h3>
  <div class="card"><div class="rules">${rulesText(r)}</div></div>${sum(r.te,"September")}
  <div class="scroll" style="max-height:300px"><table><thead><tr><th class="l">September day</th><th>profit</th><th>running</th></tr></thead><tbody>${part("te",r.ted,D.test[0])}</tbody></table></div>
  ${sum(r.tr,"Jul–Aug")}<div class="scroll" style="max-height:220px"><table><thead><tr><th class="l">Jul–Aug day</th><th>profit</th><th>running</th></tr></thead><tbody>${part("tr",r.trd,D.train[0])}</tbody></table></div>`;
 $("dlg").showModal()}
$("dlg-close").onclick=()=>$("dlg").close();

const num=v=>{const t=String(v).trim();if(t==="")return null;const n=Number(t);return Number.isFinite(n)?n:null};
for(const [id,key] of [["f-base","base"],["f-te","te"],["f-tr","tr"],["f-wr","wr"],["f-dd","dd"]])$(id).addEventListener("input",e=>{state[key]=num(e.target.value);if(key==="base"&&!(state.base>0))state.base=D.base;state.shown=200;render()});
for(const [id,key] of [["f-on","on"],["f-tp","tp"],["f-win","win"]])$(id).addEventListener("change",e=>{state[key]=e.target.value;state.shown=200;render()});
$("f-id").addEventListener("input",e=>{state.id=e.target.value;render()});
$("more").onclick=()=>{state.shown+=200;render()};
$("clear").onclick=()=>{for(const id of ["f-te","f-tr","f-wr","f-dd","f-on","f-tp","f-win","f-id"])$(id).value="";Object.assign(state,{te:null,tr:null,wr:null,dd:null,on:"",tp:"",win:"",id:"",shown:200});render()};
for(const v of [...new Set(D.rows.map(r=>r.c[C.on_winrate]))].sort((a,b)=>a-b))$("f-on").insertAdjacentHTML("beforeend",`<option value="${v}">${v}%</option>`);
for(const v of [...new Set(D.rows.map(r=>r.c[C.window_days]))].sort((a,b)=>a-b))$("f-win").insertAdjacentHTML("beforeend",`<option value="${v}">${v} days</option>`);
addEventListener("resize",()=>{clearTimeout(window.__rz);window.__rz=setTimeout(render,120)});
const G={classic:"Classic",preset:"Preset Confluence",sep25:"Sep 25 Strat",sep27ml:"Sep 27 ML"};
$("prov").innerHTML=`Built on <b>${D.tested.toLocaleString()}</b> strategy combinations tested on GitHub (${Object.entries(D.coins).map(([g,n])=>`${g.split(",").map(x=>G[x]||x).join(" + ")} on <b>${n.toLocaleString()}</b> coins`).join("; ")}), of which <b>${D.combos.toLocaleString()}</b> reached the loosest switch-on rule tried at some midnight. Tuned on checks from <b>${dayLabel(D.train[0])}</b> to <b>${dayLabel(D.train[1])}</b>, with nothing that closed after it; tested from <b>${dayLabel(D.test[0])}</b> to <b>${fmtWhen(D.end)}</b>. Every trade pays the fee both ways, the coin's usual slippage and funding, at ${money(D.base,false)} × ${D.lev}x = ${money(D.base*D.lev,false)} a trade.`;
$("notes").innerHTML=`How to read it: a rule set is every setting together. Each was replayed on July–August exactly the way the watcher works (every midnight: switch off what fell below its line, switch on what cleared its rules), and the one that made the most there is "Picked". September is the honest grade, because nothing from September was used to choose it. Exits are settled on the strategy's own candles (MEXC keeps only ~30 days of 1-minute candles), and a candle that touched both the target and the stop counts as the stop. The learned groups (Sep 25 Strat, Sep 27 ML) are left out: they were built from these same months, so they would make any rule look better than it is. Your rules show a slightly different September here than on the replay page (+$203.69 there): here every strategy's trades were walked from June, so a strategy that was mid-trade on Aug 01 opens and closes its later trades a little differently.`;
render();
</script>
"""


if __name__ == "__main__":
    raise SystemExit(main())
