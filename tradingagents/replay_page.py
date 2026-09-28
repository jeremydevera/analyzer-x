"""The results page of a watcher replay, built from its result JSON.

    python -m tradingagents.replay_page <run_id>   ->  ~/.tradingagents/replay/<run>.html

Every number on the page is computed in the page from the embedded trades, so
the base-margin box and the last-N-days box re-price and re-cut EVERYTHING —
tiles, both charts, the daily table and every strategy row — from one place
(CLAUDE.md kit items C and G). Dates on screen come from one JS copy of the
project format (`Sep 01, 2026 12:00am`), pinned against `fmt_when` by
tests/test_replay_page.py.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from tradingagents.positions_view import fmt_when

OUT_DIR = Path(os.path.expanduser("~/.tradingagents")) / "replay"


def payload(res: dict) -> dict:
    """What the page embeds: compact, every slot with every field (kit F)."""
    tot = res["totals"]
    return {
        "run": res.get("run"), "repo": res.get("repo"),
        "start_ms": res["summary"]["start_ms"], "end_ms": res["end_ms"],
        "start_label": fmt_when(res["summary"]["start_ms"] / 1000),
        "end_label": fmt_when(res["end_ms"] / 1000),
        "tested": tot["tested"], "written": res["combos_written"],
        "coins": tot["coins_done"], "coins_board": tot["coins_board"],
        "pairs": tot["pairs"], "machines": tot["machines"],
        "failed": tot["failed"], "short": len(tot["short"]),
        "tfs": sorted({s["tf"] for s in res["slots"]}),
        "cfg": res["cfg"], "base": 5.0, "lev": 20,
        "groups": tot.get("groups") or ["classic", "preset"],
        "slots": [{"id": s["id"], "coin": s["coin"], "tf": s["tf"],
                   "group": s.get("group", "classic"),
                   "signal": s["signal"], "th": s["th"], "sl": s["sl"],
                   "tp": s["tp"], "on": s["on_ms"], "off": s["off_ms"],
                   "on_why": s["on_why"], "off_why": s["off_why"],
                   "on_row": {k: s["on_row"][k] for k in
                              ("trades", "wins", "losses", "winrate", "profit")},
                   "t": [[t[0], t[1], t[2], t[3]] for t in s["trades"]]}
                  for s in res["slots"]],
        "events": res["events"],
    }


def build(res: dict) -> str:
    data = json.dumps(payload(res), separators=(",", ":"))
    return _HTML.replace("/*__DATA__*/null", data)


def main(argv=None) -> int:
    run = (argv or sys.argv[1:])[0]
    res = json.loads((OUT_DIR / f"{run}.json").read_text(encoding="utf-8"))
    path = OUT_DIR / f"{run}.html"
    path.write_text(build(res), encoding="utf-8")
    print(path)
    return 0


_HTML = r"""<title>Watcher Replay</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap">
<style>
:root{color-scheme:light;
 --bg:#f6f7f5;--panel:#ffffff;--ink:#15191a;--ink2:#4b5355;--ink3:#7a8386;
 --rule:#dde2df;--accent:#0f6b62;--accent-soft:#e3f0ee;
 --gain:#2a78d6;--loss:#e34948;--mid:#f0efec;--warn:#9a6300;--warn-soft:#fbf1dc;
 --sans:"Instrument Sans",system-ui,-apple-system,"Segoe UI",sans-serif;
 --mono:"JetBrains Mono",ui-monospace,Consolas,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;
 --bg:#111514;--panel:#181d1c;--ink:#eef2f0;--ink2:#b3bcb9;--ink3:#86908d;
 --rule:#2b3331;--accent:#4fb3a7;--accent-soft:#1c2f2c;
 --gain:#3987e5;--loss:#e66767;--mid:#383835;--warn:#e0a53a;--warn-soft:#2e2615}}
:root[data-theme="dark"]{color-scheme:dark;
 --bg:#111514;--panel:#181d1c;--ink:#eef2f0;--ink2:#b3bcb9;--ink3:#86908d;
 --rule:#2b3331;--accent:#4fb3a7;--accent-soft:#1c2f2c;
 --gain:#3987e5;--loss:#e66767;--mid:#383835;--warn:#e0a53a;--warn-soft:#2e2615}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);font:15px/1.5 var(--sans);margin:0;padding-inline:16px;padding-block:20px 48px}
main{max-width:1180px;margin:0 auto;display:flex;flex-direction:column;gap:22px}
h1{font-size:28px;line-height:1.15;margin:0;text-wrap:balance;letter-spacing:-.01em}
h2{font-size:17px;margin:0;text-wrap:balance}
.eyebrow{font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--accent)}
.lede{max-width:70ch;color:var(--ink2);margin:6px 0 0}
.num{font-family:var(--mono);font-variant-numeric:tabular-nums}
.panel{background:var(--panel);border:1px solid var(--rule);border-radius:10px;padding:16px}
.rules{display:flex;flex-wrap:wrap;gap:8px}
.chip{border:1px solid var(--rule);border-radius:999px;padding:3px 10px;font-size:13px;color:var(--ink2);background:var(--panel)}
.chip b{color:var(--ink);font-weight:600}
.prov{font-size:13px;color:var(--ink2);max-width:95ch}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px}
.tile{background:var(--panel);border:1px solid var(--rule);border-radius:10px;padding:12px 14px;display:flex;flex-direction:column;gap:2px}
.tile .k{font-size:12px;color:var(--ink3);letter-spacing:.02em}
.tile .v{font:600 22px/1.2 var(--mono);font-variant-numeric:tabular-nums}
.tile .s{font-size:12px;color:var(--ink2)}
.pos{color:var(--gain)}.neg{color:var(--loss)}
.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px}
.chart{position:relative}
.chart svg{width:100%;height:220px;display:block;overflow:visible}
.chart .cap{font-size:13px;color:var(--ink2);margin:2px 0 8px}
.tip{position:absolute;pointer-events:none;background:var(--panel);border:1px solid var(--rule);border-radius:8px;padding:6px 9px;font-size:12px;box-shadow:0 4px 14px rgba(0,0,0,.12);white-space:nowrap;z-index:5}
.filters{display:flex;flex-wrap:wrap;gap:10px;align-items:flex-end}
.filters label{display:flex;flex-direction:column;gap:3px;font-size:12px;color:var(--ink2)}
.filters input{width:112px;padding:6px 8px;border:1px solid var(--rule);border-radius:7px;background:var(--bg);color:var(--ink);font:13px var(--mono)}
.filters input#f-id{width:130px;text-transform:uppercase}
.filters select{padding:6px 8px;border:1px solid var(--rule);border-radius:7px;background:var(--bg);color:var(--ink);font:13px var(--sans)}
.btn{padding:7px 12px;border:1px solid var(--rule);border-radius:7px;background:var(--panel);color:var(--ink);font:500 13px var(--sans);cursor:pointer}
.btn:hover{border-color:var(--accent)}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.count{font-size:13px;color:var(--ink2)}
.count b{color:var(--ink)}
.why{font-size:12px;color:var(--warn);background:var(--warn-soft);border-radius:6px;padding:2px 8px}
.scroll{overflow-x:auto;border:1px solid var(--rule);border-radius:10px;background:var(--panel)}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:7px 10px;text-align:right;white-space:nowrap;border-bottom:1px solid var(--rule)}
th{position:sticky;top:0;background:var(--panel);font-weight:600;color:var(--ink2);font-size:12px;cursor:pointer;user-select:none}
th.l,td.l{text-align:left}
th[aria-sort="ascending"]::after{content:" ▲";color:var(--accent)}
th[aria-sort="descending"]::after{content:" ▼";color:var(--accent)}
td{font-family:var(--mono);font-variant-numeric:tabular-nums}
td.l{font-family:var(--sans)}
tbody tr:hover{background:var(--accent-soft)}
tr.click{cursor:pointer}
.id{color:var(--accent);font-family:var(--mono)}
.muted{color:var(--ink3)}
.log{display:flex;flex-direction:column;gap:10px}
.log h3{margin:0;font-size:15px}
.sum{display:flex;flex-wrap:wrap;gap:14px;font-size:13px;color:var(--ink2)}
.sum b{color:var(--ink);font-family:var(--mono)}
.total{font:600 15px var(--mono)}
dialog{border:1px solid var(--rule);border-radius:12px;background:var(--panel);color:var(--ink);padding:18px;width:min(920px,calc(100vw - 32px));max-height:86vh}
dialog::backdrop{background:rgba(0,0,0,.35)}
.events{max-height:320px;overflow:auto;font-size:13px}
.ev{display:flex;gap:10px;padding:5px 0;border-bottom:1px solid var(--rule);flex-wrap:wrap}
.ev .a{font-weight:600;min-width:84px}
.ev .a.on{color:var(--gain)}.ev .a.off{color:var(--loss)}
.note{font-size:13px;color:var(--ink2);max-width:95ch}
@media (max-width:560px){h1{font-size:23px}.tile .v{font-size:19px}}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
</style>
<main>
 <header>
  <div class="eyebrow">Strategy watcher · replay</div>
  <h1 id="verdict">What the watcher would have made</h1>
  <p class="lede" id="lede"></p>
 </header>
 <div class="rules" id="rules"></div>
 <p class="prov" id="prov"></p>
 <section class="tiles" id="tiles" aria-label="Summary"></section>
 <section class="charts">
  <div class="panel chart" id="c-day"><h2>Money made each day</h2><p class="cap">Closed trades, booked on the day they closed.</p><svg role="img" aria-label="Profit or loss each day"></svg></div>
  <div class="panel chart" id="c-run"><h2>Running total</h2><p class="cap">Everything closed so far, added up day by day.</p><svg role="img" aria-label="Running total of profit"></svg></div>
 </section>
 <section class="panel filters" aria-label="Filters">
  <label>Base margin $<input id="f-base" type="number" min="0.5" step="0.5" value="5"></label>
  <label>Last N days<input id="f-days" type="number" min="1" step="1" placeholder="all"></label>
  <label>Min win %<input id="f-wr" type="number" min="0" max="100" step="1" placeholder="any"></label>
  <label>Min profit $<input id="f-pf" type="number" step="0.5" placeholder="any"></label>
  <label>Min months green<input id="f-mg" type="number" min="0" step="1" placeholder="any"></label>
  <label>Max worst dip $<input id="f-dd" type="number" min="0" step="0.5" placeholder="any"></label>
  <label>Max TP %<input id="f-tp" type="number" min="0" step="0.1" placeholder="any"></label>
  <label>Max SL %<input id="f-sl" type="number" min="0" step="0.1" placeholder="any"></label>
  <label>Group<select id="f-grp"><option value="">every group</option><option value="classic">Classic</option><option value="preset">Preset Confluence</option><option value="sep25">Sep 25 Strat</option><option value="sep27ml">Sep 27 ML</option></select></label>
  <label>Find id<input id="f-id" type="text" placeholder="#77Y3BPFG"></label>
  <button class="btn" id="clear" type="button">Clear all</button>
 </section>
 <section class="log">
  <h2>Every day</h2>
  <div class="count" id="d-count"></div>
  <div class="scroll"><table id="t-days"><thead></thead><tbody></tbody></table></div>
 </section>
 <section class="log">
  <h2>Every strategy it switched on</h2>
  <div class="count" id="s-count"></div>
  <div class="scroll"><table id="t-slots"><thead></thead><tbody></tbody></table></div>
 </section>
 <section class="log">
  <h2>Every switch on and off</h2>
  <div class="panel events" id="events"></div>
 </section>
 <p class="note" id="notes"></p>
</main>
<dialog id="dlg" aria-labelledby="dlg-h"><div class="log" id="dlg-body"></div><p><button class="btn" id="dlg-close" type="button">Close</button></p></dialog>
<script>
const D = /*__DATA__*/null;
const MON=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
// the project's one date format (CLAUDE.md): Aug 03, 2026 8:03pm
function fmtWhen(ms){const d=new Date(ms);let h=d.getHours();const ap=h<12?"am":"pm";h=h%12||12;
 return `${MON[d.getMonth()]} ${String(d.getDate()).padStart(2,"0")}, ${d.getFullYear()} ${h}:${String(d.getMinutes()).padStart(2,"0")}${ap}`}
function dayLabel(ms){const d=new Date(ms);return `${MON[d.getMonth()]} ${String(d.getDate()).padStart(2,"0")}, ${d.getFullYear()}`}
function dayKey(ms){const d=new Date(ms);return d.getFullYear()*10000+(d.getMonth()+1)*100+d.getDate()}
function midnight(ms){const d=new Date(ms);return new Date(d.getFullYear(),d.getMonth(),d.getDate()).getTime()}
const money=(v,sign=true)=>(sign&&v>0?"+":"")+(v<0?"-":"")+"$"+Math.abs(v).toFixed(2);
const pct=v=>v.toFixed(1)+"%";
const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

const state={base:5,days:0,wr:null,pf:null,mg:null,dd:null,tp:null,sl:null,grp:"",id:"",sort:{k:"profit",dir:-1}};
const GROUP_LABEL={classic:"Classic",preset:"Preset Confluence",sep25:"Sep 25 Strat",sep27ml:"Sep 27 ML"};

function scale(){return state.base/D.base}
function windowStart(){return state.days>0?midnight(D.end_ms)-(state.days-1)*86400000:D.start_ms}

/* one slot, priced at the current base margin over the current window */
function slotStats(s){
 const k=scale(), w0=windowStart();
 const closed=s.t.filter(t=>t[3]&&t[1]>=w0).sort((a,b)=>a[1]-b[1]);
 const open=s.t.filter(t=>!t[3]).length;
 let wins=0,profit=0,run=0,n=0,worst=0,wn=0;const months={};
 for(const t of closed){const p=t[2]*k;profit+=p;if(p>0){wins++;run=0;n=0}else{run+=p;n++;if(run<worst){worst=run;wn=n}}
  const d=new Date(t[1]);const m=d.getFullYear()*100+d.getMonth();months[m]=(months[m]||0)+p}
 const on=Math.max(s.on,w0), off=s.off==null?D.end_ms:s.off;
 const liveDays=Math.max(0,(Math.min(off,D.end_ms)-on)/86400000);
 return {closed:closed.length,wins,losses:closed.length-wins,profit,worst,wn,open,
  winrate:closed.length?100*wins/closed.length:0,green:Object.values(months).filter(v=>v>0).length,
  months:Object.keys(months).length,perDay:liveDays>0?closed.length/liveDays:0,trades:closed}
}

function filtered(){
 const want=state.id.replace(/^#+/,"").trim().toUpperCase();
 const rows=D.slots.map((s,i)=>({s,i,st:slotStats(s)}));
 if(want) return {rows:rows.filter(r=>r.s.id===want),names:[`id #${want} (overrides the other filters)`],byId:true};
 const names=[];let out=rows;
 const f=(on,label,pred)=>{if(on){names.push(label);out=out.filter(pred)}};
 f(state.wr!=null,`win ≥ ${state.wr}%`,r=>r.st.winrate>=state.wr);
 f(state.pf!=null,`profit ≥ ${money(state.pf,false)}`,r=>r.st.profit>=state.pf);
 f(state.mg!=null,`≥ ${state.mg} month(s) green`,r=>r.st.green>=state.mg);
 f(state.dd!=null,`worst dip ≤ ${money(state.dd,false)}`,r=>-r.st.worst<=state.dd);
 f(state.tp!=null,`TP ≤ ${state.tp}%`,r=>r.s.tp<=state.tp);
 f(state.sl!=null,`SL ≤ ${state.sl}%`,r=>r.s.sl<=state.sl);
 f(!!state.grp,`group ${GROUP_LABEL[state.grp]}`,r=>r.s.group===state.grp);
 if(state.days>0) names.unshift(`last ${state.days} day(s)`);
 return {rows:out,names,byId:false};
}

/* the days, rebuilt from the kept strategies' trades and the switch log */
function days(rows){
 const w0=windowStart(),k=scale(),map=new Map();
 for(let t=midnight(Math.max(D.start_ms,w0));t<=D.end_ms;t=midnight(t+36*3600000)){
  map.set(dayKey(t),{at:t,on:0,off:0,running:0,closed:0,wins:0,losses:0,pnl:0,tps:[],sls:[]})}
 const ids=new Set(rows.map(r=>r.s.id));
 for(const e of D.events){if(!ids.has(e.id))continue;const d=map.get(dayKey(e.at));if(d)d[e.action]++}
 for(const r of rows){for(const t of r.st.trades){const d=map.get(dayKey(t[1]));if(!d)continue;const p=t[2]*k;
   d.closed++;d[p>0?"wins":"losses"]++;d.pnl+=p;d.tps.push(r.s.tp);d.sls.push(r.s.sl)}}
 const list=[...map.values()].sort((a,b)=>a.at-b.at);let tot=0;
 for(const d of list){d.running=rows.filter(r=>r.s.on<=d.at&&(r.s.off==null||r.s.off>d.at)).length;tot+=d.pnl;d.total=tot}
 return list;
}

function streakAll(rows){ // the worst unbroken run of losses across the whole book, in close order
 const all=rows.flatMap(r=>r.st.trades.map(t=>t[2]*scale())); // per slot order is already by close
 const ts=rows.flatMap(r=>r.st.trades.map(t=>t[1]));const idx=all.map((_,i)=>i).sort((a,b)=>ts[a]-ts[b]);
 let run=0,n=0,worst=0,wn=0;for(const i of idx){const p=all[i];if(p>0){run=0;n=0}else{run+=p;n++;if(run<worst){worst=run;wn=n}}}
 return {worst,wn};
}

function render(){
 const F=filtered(),rows=F.rows,ds=days(rows);
 const closed=rows.reduce((a,r)=>a+r.st.closed,0),wins=rows.reduce((a,r)=>a+r.st.wins,0);
 const profit=rows.reduce((a,r)=>a+r.st.profit,0),open=rows.reduce((a,r)=>a+r.st.open,0);
 const st=streakAll(rows);
 const worstDay=ds.reduce((m,d)=>d.pnl<m.pnl?d:m,{pnl:0,at:null}),bestDay=ds.reduce((m,d)=>d.pnl>m.pnl?d:m,{pnl:0,at:null});
 const green=ds.filter(d=>d.pnl>0).length,red=ds.filter(d=>d.pnl<0).length;
 const w0=windowStart();
 $("verdict").textContent=`${profit>=0?"Made":"Lost"} ${money(Math.abs(profit),false)} from ${dayLabel(Math.max(D.start_ms,w0))} to ${dayLabel(D.end_ms)}`;
 $("lede").textContent=`Replay of the watcher as if it had been switched on ${dayLabel(D.start_ms)}: every midnight it switched off anything under ${D.cfg.off_winrate}% over the previous 30 days and switched on new strategies that cleared its rules. ${rows.length} strateg${rows.length===1?"y":"ies"} ${F.names.length?"match the filters":"were switched on"}; ${closed.toLocaleString()} practice trades closed (${wins} won, ${closed-wins} lost) at ${money(state.base,false)} a trade.`;
 $("tiles").innerHTML=[
  ["Total profit",`<span class="${profit>=0?"pos":"neg"}">${money(profit)}</span>`,`${open} trade(s) still open, not counted`],
  ["Trades closed",closed.toLocaleString(),`${wins} won · ${closed-wins} lost · ${closed?pct(100*wins/closed):"—"} won`],
  ["Strategies switched on",rows.length.toLocaleString(),`${new Set(rows.map(r=>r.s.id)).size} different ids`],
  ["Days up / down",`${green} / ${red}`,`of ${ds.length} day(s)`],
  ["Worst day",worstDay.at?`<span class="neg">${money(worstDay.pnl)}</span>`:"—",worstDay.at?dayLabel(worstDay.at):"no losing day"],
  ["Best day",bestDay.at?`<span class="pos">${money(bestDay.pnl)}</span>`:"—",bestDay.at?dayLabel(bestDay.at):"no winning day"],
  ["Worst losing run",st.wn?`<span class="neg">${money(st.worst)}</span>`:"—",st.wn?`${st.wn} losing trades in a row, all strategies, in closing order`:"never two losses in a row"],
 ].map(([k,v,s])=>`<div class="tile"><span class="k">${k}</span><span class="v">${v}</span><span class="s">${s}</span></div>`).join("");
 drawBars(ds);drawLine(ds);
 renderDays(ds,F);renderSlots(rows,F);renderEvents(rows);
 if(F.byId&&rows.length===1&&!openedFor){openedFor=rows[0].s.id;openLog(rows[0])}
 if(!F.byId)openedFor="";
}
let openedFor="";

/* ---------- charts: one axis each, recessive grid, hover per mark ---------- */
function niceTicks(lo,hi){const span=Math.max(1e-9,hi-lo),step0=span/4,p=Math.pow(10,Math.floor(Math.log10(step0)));
 const step=[1,2,2.5,5,10].map(m=>m*p).find(s=>s>=step0);const out=[];const top=Math.ceil(hi/step-1e-9)*step;for(let v=Math.floor(lo/step)*step;v<=top+1e-9;v+=step)out.push(+v.toFixed(6));return out}
function frame(svg){const r=svg.getBoundingClientRect();return {W:Math.max(280,r.width),H:220,L:58,R:12,T:10,B:28}}
function axis(svg,f,ticks,y){let g="";for(const v of ticks){const yy=y(v);g+=`<line x1="${f.L}" x2="${f.W-f.R}" y1="${yy}" y2="${yy}" stroke="var(--rule)" stroke-width="${v===0?1.5:1}"/><text x="${f.L-8}" y="${yy+4}" text-anchor="end" font-size="11" fill="var(--ink3)" font-family="var(--mono)">${money(v)}</text>`}return g}
function xlabels(f,ds,x){if(!ds.length)return"";const every=Math.ceil(ds.length/(f.W<480?4:7));let g="";
 ds.forEach((d,i)=>{if(i%every===0||i===ds.length-1){g+=`<text x="${x(i)}" y="${f.H-8}" text-anchor="middle" font-size="11" fill="var(--ink3)">${MON[new Date(d.at).getMonth()]} ${new Date(d.at).getDate()}</text>`}});return g}
function tipAt(box,html,px,py){let t=box.querySelector(".tip");if(!t){t=document.createElement("div");t.className="tip";box.appendChild(t)}
 t.innerHTML=html;t.hidden=false;const bw=box.clientWidth;const tw=t.offsetWidth;t.style.left=Math.min(bw-tw-4,Math.max(4,px-tw/2))+"px";t.style.top=Math.max(0,py-54)+"px"}
function hideTip(box){const t=box.querySelector(".tip");if(t)t.hidden=true}
function dayTip(d){return `<b>${dayLabel(d.at)}</b><br>${money(d.pnl)} · ${d.closed} closed (${d.wins}W/${d.losses}L)<br>running total ${money(d.total)}`}
function drawBars(ds){const box=$("c-day"),svg=box.querySelector("svg"),f=frame(svg);svg.setAttribute("viewBox",`0 0 ${f.W} ${f.H}`);
 const lo=Math.min(0,...ds.map(d=>d.pnl)),hi=Math.max(0,...ds.map(d=>d.pnl));const ticks=niceTicks(lo,hi);const tl=ticks[0],th=ticks[ticks.length-1];
 const y=v=>f.T+(th-v)/(th-tl||1)*(f.H-f.T-f.B);const bw=(f.W-f.L-f.R)/Math.max(1,ds.length);const x=i=>f.L+bw*(i+.5);
 let g=axis(svg,f,ticks,y);const barW=Math.max(2,Math.min(22,bw-2));
 ds.forEach((d,i)=>{if(!d.pnl)return;const y0=y(0),y1=y(d.pnl),top=Math.min(y0,y1),h=Math.max(1,Math.abs(y1-y0));const r=Math.min(4,h/2,barW/2);
  const c=d.pnl>0?"var(--gain)":"var(--loss)";const xx=x(i)-barW/2;
  g+=d.pnl>0?`<path d="M${xx},${y0}V${top+r}Q${xx},${top} ${xx+r},${top}H${xx+barW-r}Q${xx+barW},${top} ${xx+barW},${top+r}V${y0}Z" fill="${c}"/>`
   :`<path d="M${xx},${y0}V${top+h-r}Q${xx},${top+h} ${xx+r},${top+h}H${xx+barW-r}Q${xx+barW},${top+h} ${xx+barW},${top+h-r}V${y0}Z" fill="${c}"/>`});
 ds.forEach((d,i)=>{g+=`<rect class="hit" data-i="${i}" x="${f.L+bw*i}" y="${f.T}" width="${bw}" height="${f.H-f.T-f.B}" fill="transparent"/>`});
 g+=xlabels(f,ds,x);svg.innerHTML=g;
 svg.querySelectorAll(".hit").forEach(el=>{el.addEventListener("mousemove",ev=>{const d=ds[+el.dataset.i];const r=box.getBoundingClientRect();tipAt(box,dayTip(d),ev.clientX-r.left,ev.clientY-r.top)});el.addEventListener("mouseleave",()=>hideTip(box))})}
function drawLine(ds){const box=$("c-run"),svg=box.querySelector("svg"),f=frame(svg);svg.setAttribute("viewBox",`0 0 ${f.W} ${f.H}`);
 const vals=ds.map(d=>d.total);const lo=Math.min(0,...vals),hi=Math.max(0,...vals);const ticks=niceTicks(lo,hi);const tl=ticks[0],th=ticks[ticks.length-1];
 const y=v=>f.T+(th-v)/(th-tl||1)*(f.H-f.T-f.B);const n=Math.max(1,ds.length-1);const x=i=>f.L+(f.W-f.L-f.R)*(ds.length>1?i/n:.5);
 let g=axis(svg,f,ticks,y);
 if(ds.length){const pts=ds.map((d,i)=>`${x(i)},${y(d.total)}`).join(" ");const last=ds[ds.length-1];const c=last.total>=0?"var(--gain)":"var(--loss)";
  g+=`<polygon points="${x(0)},${y(0)} ${pts} ${x(ds.length-1)},${y(0)}" fill="${c}" opacity=".12"/>`;
  g+=`<polyline points="${pts}" fill="none" stroke="${c}" stroke-width="2" stroke-linejoin="round"/>`;
  g+=`<circle cx="${x(ds.length-1)}" cy="${y(last.total)}" r="4" fill="${c}" stroke="var(--panel)" stroke-width="2"/>`;
  g+=`<text x="${x(ds.length-1)-6}" y="${y(last.total)-9}" text-anchor="end" font-size="12" font-family="var(--mono)" fill="var(--ink)">${money(last.total)}</text>`}
 g+=`<line class="cross" x1="0" x2="0" y1="${f.T}" y2="${f.H-f.B}" stroke="var(--ink3)" stroke-dasharray="3 3" visibility="hidden"/>`;
 g+=`<rect class="hitall" x="${f.L}" y="${f.T}" width="${f.W-f.L-f.R}" height="${f.H-f.T-f.B}" fill="transparent"/>`;g+=xlabels(f,ds,x);svg.innerHTML=g;
 const cross=svg.querySelector(".cross"),hit=svg.querySelector(".hitall");
 hit.addEventListener("mousemove",ev=>{if(!ds.length)return;const r=svg.getBoundingClientRect();const px=(ev.clientX-r.left)*(f.W/r.width);
  const i=Math.max(0,Math.min(ds.length-1,Math.round((px-f.L)/((f.W-f.L-f.R)/n))));cross.setAttribute("x1",x(i));cross.setAttribute("x2",x(i));cross.setAttribute("visibility","visible");
  const b=box.getBoundingClientRect();tipAt(box,dayTip(ds[i]),ev.clientX-b.left,ev.clientY-b.top)});
 hit.addEventListener("mouseleave",()=>{cross.setAttribute("visibility","hidden");hideTip(box)})}

/* ---------- tables ---------- */
function range(a){if(!a.length)return"—";const lo=Math.min(...a),hi=Math.max(...a);return lo===hi?`${lo}%`:`${lo}–${hi}%`}
function renderDays(ds,F){
 $("t-days").querySelector("thead").innerHTML=`<tr><th class="l">day</th><th>running</th><th>switched on</th><th>switched off</th><th>trades</th><th>wins</th><th>losses</th><th>TP</th><th>SL</th><th>lev</th><th>profit that day</th><th>running total</th></tr>`;
 $("t-days").querySelector("tbody").innerHTML=ds.map(d=>`<tr><td class="l">${dayLabel(d.at)}</td><td>${d.running}</td><td>${d.on}</td><td>${d.off}</td><td>${d.closed}</td><td>${d.wins}</td><td>${d.losses}</td><td>${range(d.tps)}</td><td>${range(d.sls)}</td><td>${D.lev}x</td><td class="${d.pnl>0?"pos":d.pnl<0?"neg":""}">${money(d.pnl)}</td><td class="${d.total>0?"pos":d.total<0?"neg":""}">${money(d.total)}</td></tr>`).join("");
 const w0=windowStart();
 $("d-count").innerHTML=`<b>${ds.length}</b> day(s), ${dayLabel(Math.max(D.start_ms,w0))} to ${fmtWhen(D.end_ms)}${F.names.length?" · "+esc(F.names.join(" AND ")):""} · at <b>${money(state.base,false)}</b> margin × ${D.lev}x = <b>${money(state.base*D.lev,false)}</b> a trade`;
}
const COLS=[["id","id",1],["coin","coin",1],["tf","tf",1],["signal","signal",1],["group","group",1],["tp","TP %"],["sl","SL %"],["lev","lev"],["closed","trades"],["perDay","trades/day"],["wins","wins"],["losses","losses"],["winrate","win %"],["worst","worst losing run"],["green","months green"],["profit","PROFIT $"],["on","switched on",1],["off","switched off",1],["open","open"]];
function val(r,k){if(k in r.st)return r.st[k];if(k==="lev")return D.lev;if(k==="off")return r.s.off??Infinity;return r.s[k]}
function renderSlots(rows,F){
 const th=$("t-slots").querySelector("thead");
 th.innerHTML="<tr>"+COLS.map(([k,l,left])=>`<th class="${left?"l":""}" data-k="${k}" aria-sort="${state.sort.k===k?(state.sort.dir>0?"ascending":"descending"):"none"}">${l}</th>`).join("")+"</tr>";
 th.querySelectorAll("th").forEach(h=>h.onclick=()=>{const k=h.dataset.k;state.sort=state.sort.k===k?{k,dir:-state.sort.dir}:{k,dir:["id","coin","tf","signal","group","on","off"].includes(k)?1:-1};render()});
 const sorted=[...rows].sort((a,b)=>{const x=val(a,state.sort.k),y=val(b,state.sort.k);return (x>y?1:x<y?-1:0)*state.sort.dir});
 $("t-slots").querySelector("tbody").innerHTML=sorted.map(r=>{const s=r.s,st=r.st;return `<tr class="click" data-i="${r.i}" tabindex="0">
  <td class="l id">#${s.id}</td><td class="l">${s.coin}</td><td class="l">${s.tf}</td><td class="l">${esc(s.signal)}${s.th?` ${s.th}`:""}</td><td class="l">${GROUP_LABEL[s.group]||s.group}</td>
  <td>${s.tp}</td><td>${s.sl}</td><td>${D.lev}x</td><td>${st.closed}</td><td>${st.perDay.toFixed(2)}</td><td>${st.wins}</td><td>${st.losses}</td><td>${st.closed?pct(st.winrate):"—"}</td>
  <td class="${st.worst<0?"neg":""}">${st.wn?`${money(st.worst)} (${st.wn})`:"—"}</td><td>${st.green}/${st.months}</td>
  <td class="${st.profit>0?"pos":st.profit<0?"neg":""}">${money(st.profit)}</td>
  <td class="l">${fmtWhen(s.on)}</td><td class="l">${s.off==null?'<span class="muted">still on</span>':fmtWhen(s.off)}</td><td>${st.open}</td></tr>`}).join("");
 $("t-slots").querySelectorAll("tr.click").forEach(tr=>{const go=()=>openLog(rows.find(r=>r.i===+tr.dataset.i));tr.onclick=go;tr.onkeydown=e=>{if(e.key==="Enter")go()}});
 const why=[];
 if(!F.byId){
  if(state.wr!=null&&rows.every(r=>r.st.winrate>=state.wr)&&D.slots.length===rows.length)why.push(`every strategy already wins ${state.wr}% or more here`);
  if(state.tp!=null&&D.slots.every(s=>s.tp<=state.tp))why.push(`no strategy has a TP above ${state.tp}%`);
  if(state.sl!=null&&D.slots.every(s=>s.sl<=state.sl))why.push(`no strategy has an SL above ${state.sl}%`);
 }
 $("s-count").innerHTML=`<b>${rows.length}</b> of ${D.slots.length} switch-on(s)${F.names.length?" · "+esc(F.names.join(" AND ")):""}`+
  ` · chosen from <b>${D.tested.toLocaleString()}</b> combinations tested (${D.written.toLocaleString()} could pass at some check)`+
  (why.length?` <span class="why">${esc(why.join("; "))} — this filter removes nothing</span>`:"")+
  (rows.length===0&&F.byId?` <span class="why">#${esc(state.id.replace(/^#+/,"").toUpperCase())} was never switched on in this replay</span>`:"");
}
function renderEvents(rows){const ids=new Set(rows.map(r=>r.s.id));
 $("events").innerHTML=D.events.filter(e=>ids.has(e.id)).map(e=>`<div class="ev"><span class="num muted">${fmtWhen(e.at)}</span><span class="a ${e.action}">${e.action==="on"?"switched on":"switched off"}</span><span class="id">#${e.id}</span><span>${e.coin}</span><span class="muted">${esc(e.why)}</span></div>`).join("")||'<div class="muted">nothing in the current view</div>'}

function openLog(r){if(!r)return;const s=r.s,st=r.st,k=scale();
 const rows=[...st.trades].sort((a,b)=>a[0]-b[0]);let run=0;
 $("dlg-body").innerHTML=`<h3 id="dlg-h"><span class="id">#${s.id}</span> ${s.coin} ${s.tf} ${esc(s.signal)} (${GROUP_LABEL[s.group]||s.group}) · TP ${s.tp}% / SL ${s.sl}% · ${D.lev}x · ${money(state.base,false)} margin (${money(state.base*D.lev,false)} a trade)</h3>
  <div class="sum"><span>switched on <b>${fmtWhen(s.on)}</b></span><span>${s.off==null?"still on":`switched off <b>${fmtWhen(s.off)}</b>`}</span></div>
  <div class="sum"><span>why on: ${esc(s.on_why)}</span>${s.off_why?`<span>why off: ${esc(s.off_why)}</span>`:""}</div>
  <div class="scroll"><table><thead><tr><th class="l">#</th><th class="l">entered</th><th class="l">closed</th><th>profit</th><th>running</th></tr></thead><tbody>${
   rows.map((t,i)=>{const p=t[2]*k;run+=p;return `<tr><td class="l">${i+1}</td><td class="l">${fmtWhen(t[0])}</td><td class="l">${fmtWhen(t[1])}</td><td class="${p>0?"pos":"neg"}">${money(p)}</td><td>${money(run)}</td></tr>`}).join("")
   ||'<tr><td class="l muted" colspan="5">no trade closed in this window</td></tr>'}</tbody></table></div>
  <div class="sum"><span>TOTAL PROFIT <b class="total ${st.profit>=0?"pos":"neg"}">${money(st.profit)}</b></span><span>${st.closed} trades · ${st.wins} won · ${st.losses} lost</span><span>worst losing run <b>${st.wn?`${money(st.worst)} over ${st.wn}`:"none"}</b></span>${st.open?`<span>${st.open} still open, not counted</span>`:""}</div>`;
 $("dlg").showModal()}
$("dlg-close").onclick=()=>$("dlg").close();

/* ---------- controls ---------- */
const num=v=>{const t=String(v).trim();if(t==="")return null;const n=Number(t);return Number.isFinite(n)?n:null};
function bind(id,key,parse=num){$(id).addEventListener("input",e=>{state[key]=parse(e.target.value);if(key==="base"&&!(state.base>0))state.base=D.base;if(key==="days")state.days=state.days>0?Math.floor(state.days):0;render()})}
bind("f-base","base");bind("f-days","days");bind("f-wr","wr");bind("f-pf","pf");bind("f-mg","mg");bind("f-dd","dd");bind("f-tp","tp");bind("f-sl","sl");bind("f-id","id",v=>String(v));$("f-grp").addEventListener("change",e=>{state.grp=e.target.value;render()});
$("clear").onclick=()=>{for(const id of ["f-days","f-wr","f-pf","f-mg","f-dd","f-tp","f-sl","f-id","f-grp"])$(id).value="";Object.assign(state,{days:0,wr:null,pf:null,mg:null,dd:null,tp:null,sl:null,grp:"",id:""});render()};
addEventListener("resize",()=>{clearTimeout(window.__rz);window.__rz=setTimeout(render,120)});

/* ---------- static text ---------- */
const c=D.cfg;
$("rules").innerHTML=[`switch on at <b>${c.on_winrate}%+</b> over 30 days`,`switch off under <b>${c.off_winrate}%</b>`,`TP <b>wider than</b> SL`,`<b>${c.min_trades}+</b> trades in 30 days`,`made money over those 30 days`,`up to <b>${c.max_slots}</b> at once · <b>${c.max_per_coin}</b> per coin · <b>${c.max_new_per_day}</b> new a day`,`<b>${c.cooldown_days}</b>-day wait after a switch-off`,`practice account · flat <b>$${D.base}</b> × ${D.lev}x`].map(t=>`<span class="chip">${t}</span>`).join("");
const learned=D.slots.filter(s=>s.group==="sep25"||s.group==="sep27ml");
$("prov").innerHTML=`Groups walked: <b>${D.groups.map(g=>GROUP_LABEL[g]||g).join(", ")}</b>${D.groups.includes("sep27ml")&&!D.slots.some(s=>s.group==="sep27ml")?" (Sep 27 ML had no finished models yet, so it added nothing)":""}. GitHub run(s) <b>${esc(D.run)}</b> (${esc(D.repo)}): <b>${D.tested.toLocaleString()}</b> strategy combinations tested over <b>${D.coins.toLocaleString()}</b> of ${D.coins_board.toLocaleString()} coins on ${D.machines} machines, 15m/30m/1h/4h/1d, from 30 days before ${dayLabel(D.start_ms)} to <b>${fmtWhen(D.end_ms)}</b>. ${D.written.toLocaleString()} of them cleared the switch-on rules at some midnight. Every trade is charged the fee both ways, the coin's usual slippage and funding, at ${money(D.base,false)} margin × ${D.lev}x = ${money(D.base*D.lev,false)} a trade.${Object.keys(D.failed).length?` ${Object.keys(D.failed).length} coin(s) could not be measured: ${esc(Object.keys(D.failed).slice(0,8).join(", "))}${Object.keys(D.failed).length>8?"…":""}.`:""}`;
$("notes").innerHTML=`How to read it: each midnight the replay looked only at trades that had already closed in the 30 days before it — nothing from later could switch a strategy on. A switched-on strategy earns the trades it opened while on; a trade still open when it was switched off finishes normally and counts. Exits are settled on the strategy's own candles (15 minutes to 1 day): MEXC keeps only about 30 days of 1-minute candles, so August cannot be settled minute by minute the way Backtest v2 is, and when one candle touched both the target and the stop it is counted as the stop. The live watcher also re-reads the order book before each switch-on and blocks a second position on the same coin going the other way; the replay uses each coin's usual cost instead and lets every strategy trade on its own. Coins that were delisted before today are not in it.`+(learned.length?` <b>${learned.length} of these strategies are learned formulas (Sep 25 Strat / Sep 27 ML).</b> Those were built from candles that include August, so on Sep 01 they are judged on the same days they were learned from, and their results here look better than they would have been. Filter by group to see the rest on their own.`:"");
render();
</script>
"""


if __name__ == "__main__":
    raise SystemExit(main())
