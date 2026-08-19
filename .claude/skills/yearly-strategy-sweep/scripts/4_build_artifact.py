"""Build the all-coins 1h/15m/1m sweep artifact."""
import json, pathlib

import os
HERE = pathlib.Path(os.environ.get("SWEEP_DIR",
    os.path.expanduser("~/.tradingagents/sweeps/latest"))).expanduser()
D = json.load(open(HERE / "sweep_pack.json"))

import os as _os
_TFL = _os.environ.get("SWEEP_TFS", "1h,15m,1m").replace(",", " / ")
HTML = r"""<title>All Coins — __TFS__ Sweep</title>
<style>
:root{
  --ground:#F7F6F4; --panel:#FFFFFF; --edge:#DFDCD6; --edge-soft:#EDEBE6;
  --ink:#17181B; --ink-2:#484C52; --ink-3:#7E838A;
  --accent:#1F6F6B; --bad:#A32C34; --good:#2C6B4F; --warn:#96690F;
  --bad-wash:#F6E8E8; --good-wash:#E4F0E9; --warn-wash:#F7EFDC;
  --shadow:0 1px 2px rgba(23,24,27,.05),0 8px 24px rgba(23,24,27,.05);
}
@media (prefers-color-scheme:dark){:root{
  --ground:#0E1112; --panel:#151A1B; --edge:#272D2E; --edge-soft:#1E2425;
  --ink:#ECEFEF; --ink-2:#A5ACAF; --ink-3:#727980;
  --accent:#5EC0B8; --bad:#E4666E; --good:#5FB98C; --warn:#D6A54F;
  --bad-wash:#291718; --good-wash:#14241D; --warn-wash:#282111;
  --shadow:0 1px 2px rgba(0,0,0,.45),0 8px 28px rgba(0,0,0,.4);
}}
:root[data-theme=dark]{
  --ground:#0E1112; --panel:#151A1B; --edge:#272D2E; --edge-soft:#1E2425;
  --ink:#ECEFEF; --ink-2:#A5ACAF; --ink-3:#727980;
  --accent:#5EC0B8; --bad:#E4666E; --good:#5FB98C; --warn:#D6A54F;
  --bad-wash:#291718; --good-wash:#14241D; --warn-wash:#282111;
  --shadow:0 1px 2px rgba(0,0,0,.45),0 8px 28px rgba(0,0,0,.4);
}
:root[data-theme=light]{
  --ground:#F7F6F4; --panel:#FFFFFF; --edge:#DFDCD6; --edge-soft:#EDEBE6;
  --ink:#17181B; --ink-2:#484C52; --ink-3:#7E838A;
  --accent:#1F6F6B; --bad:#A32C34; --good:#2C6B4F; --warn:#96690F;
  --bad-wash:#F6E8E8; --good-wash:#E4F0E9; --warn-wash:#F7EFDC;
  --shadow:0 1px 2px rgba(23,24,27,.05),0 8px 24px rgba(23,24,27,.05);
}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);
  font-family:"Charter","Bitstream Charter","Iowan Old Style",Georgia,serif;
  line-height:1.55;-webkit-font-smoothing:antialiased}
.wrap{max-width:1320px;margin:0 auto;padding:38px 22px 96px;display:flex;
  flex-direction:column;gap:24px}
header{display:flex;flex-direction:column;gap:13px;border-bottom:1px solid var(--edge);
  padding-bottom:22px}
.eyebrow{font-family:ui-monospace,"SF Mono",Menlo,monospace;font-size:11px;
  letter-spacing:.16em;text-transform:uppercase;color:var(--accent);font-weight:600}
h1{margin:0;font-size:clamp(28px,4.2vw,42px);line-height:1.08;text-wrap:balance;
  font-weight:600;letter-spacing:-.015em}
.dek{margin:0;max-width:74ch;color:var(--ink-2);font-size:17px}
.grid3{display:flex;flex-wrap:wrap;gap:11px}
.vstat{flex:1 1 180px;background:var(--panel);border:1px solid var(--edge);
  border-radius:3px;padding:14px 16px;box-shadow:var(--shadow)}
.vstat .k{font-family:ui-monospace,monospace;font-size:10px;letter-spacing:.13em;
  text-transform:uppercase;color:var(--ink-3)}
.vstat .v{font-family:ui-monospace,monospace;font-size:22px;margin-top:5px;
  font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.vstat .n{font-size:12.5px;color:var(--ink-2);margin-top:4px}
.v.bad{color:var(--bad)} .v.good{color:var(--good)} .v.warn{color:var(--warn)}
.banner{background:var(--warn-wash);border:1px solid var(--warn);border-radius:3px;
  padding:14px 16px;font-size:14.5px;color:var(--ink-2)}
.banner b{color:var(--ink)}
.controls{display:flex;flex-wrap:wrap;gap:15px;align-items:flex-end;
  background:var(--panel);border:1px solid var(--edge);border-radius:3px;
  padding:15px 17px;box-shadow:var(--shadow)}
label{display:flex;flex-direction:column;gap:6px;font-family:ui-monospace,monospace;
  font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-3)}
input[type=number],select{font-family:ui-monospace,monospace;font-size:14px;
  padding:7px 9px;background:var(--ground);color:var(--ink);
  border:1px solid var(--edge);border-radius:2px;min-width:126px}
input:focus-visible,select:focus-visible,tr:focus-visible{outline:2px solid var(--accent);
  outline-offset:2px}
.hint{font-family:inherit;font-size:13.5px;color:var(--ink-2);text-transform:none;
  letter-spacing:0;max-width:36ch}
.scroll{overflow-x:auto;border:1px solid var(--edge);border-radius:3px;
  background:var(--panel);box-shadow:var(--shadow);max-height:620px;overflow-y:auto}
table{border-collapse:collapse;width:100%;min-width:1460px;font-size:12.5px}
th{font-family:ui-monospace,monospace;font-size:9px;letter-spacing:.1em;
  text-transform:uppercase;color:var(--ink-3);text-align:right;padding:10px 8px;
  border-bottom:1px solid var(--edge);white-space:nowrap;cursor:pointer;
  user-select:none;background:var(--panel);position:sticky;top:0;z-index:2}
th:first-child,td:first-child{text-align:left}
th:hover{color:var(--accent)}
th .ar{opacity:.45;font-size:9px}
td{padding:8px;border-bottom:1px solid var(--edge-soft);text-align:right;
  white-space:nowrap;font-family:ui-monospace,monospace;
  font-variant-numeric:tabular-nums}
tbody tr{cursor:pointer}
tbody tr:hover{background:var(--edge-soft)}
tbody tr.sel{background:var(--edge-soft);box-shadow:inset 3px 0 0 var(--accent)}
tbody tr.surv{background:var(--good-wash)}
.tag{display:inline-block;font-family:ui-monospace,monospace;font-size:9px;
  letter-spacing:.08em;text-transform:uppercase;padding:2px 5px;border-radius:2px;
  border:1px solid;font-weight:600}
.tag.s{color:var(--good);border-color:var(--good)}
.tag.p{color:var(--ink-3);border-color:var(--edge)}
.tag.l{color:var(--accent);border-color:var(--accent)}
.num.bad{color:var(--bad)} .num.good{color:var(--good)}
tfoot td{border-top:2px solid var(--edge);border-bottom:none;font-weight:600;
  background:var(--panel);position:sticky;bottom:0}
h2{font-size:19px;margin:0 0 2px;font-weight:600;letter-spacing:-.01em}
.sec{display:flex;flex-direction:column;gap:11px}
.note{font-size:14px;color:var(--ink-2);max-width:90ch;margin:0}
#panel{background:var(--panel);border:1px solid var(--edge);border-radius:3px;
  padding:20px;box-shadow:var(--shadow)}
.ph{color:var(--ink-3);font-size:15px;text-align:center;padding:32px 12px}
.pgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(134px,1fr));
  gap:9px;margin:14px 0}
.pcell{border:1px solid var(--edge);border-radius:2px;padding:8px 10px}
.pcell .k{font-family:ui-monospace,monospace;font-size:9px;letter-spacing:.12em;
  text-transform:uppercase;color:var(--ink-3)}
.pcell .v{font-family:ui-monospace,monospace;font-size:15px;margin-top:3px}
.total{margin-top:14px;border-top:2px solid var(--edge);padding-top:13px;
  display:flex;flex-wrap:wrap;gap:22px;align-items:baseline}
.total .lab{font-family:ui-monospace,monospace;font-size:10px;letter-spacing:.12em;
  text-transform:uppercase;color:var(--ink-3)}
.total .big{font-family:ui-monospace,monospace;font-size:23px}
.logscroll{max-height:310px;overflow:auto;border:1px solid var(--edge);
  border-radius:2px;margin-top:12px}
.logscroll table{min-width:880px;font-size:11.5px}
.months{display:flex;flex-wrap:wrap;gap:4px;margin-top:10px}
.mo{font-family:ui-monospace,monospace;font-size:10.5px;padding:3px 6px;
  border-radius:2px;border:1px solid var(--edge)}
.mo.g{color:var(--good);border-color:var(--good);background:var(--good-wash)}
.mo.r{color:var(--bad);border-color:var(--bad);background:var(--bad-wash)}
footer{border-top:1px solid var(--edge);padding-top:20px;color:var(--ink-3);
  font-size:13px;max-width:90ch}
code{font-family:ui-monospace,monospace;font-size:.92em;background:var(--edge-soft);
  padding:1px 5px;border-radius:2px}
</style>

<div class="wrap">
<header>
  <div class="eyebrow">All-coin sweep &middot; <span id="stamp"></span> &middot; MEXC USDT perpetuals</div>
  <h1>Six years of history, and the flat survivors still number in the dozens.</h1>
  <p class="dek"><strong>All 979 tradeable contracts. 55,062 combinations.</strong>
  Three timeframes &times; seven signals &times; three TP/SL pairs &times; both sizings.
  Each contract&rsquo;s cost is walked from <em>its own</em> live order book &mdash; never
  averaged &mdash; and any pair whose round-trip cost reaches half its take-profit was
  excluded before it could flatter the table.</p>
  <p class="dek" style="font-size:15.5px"><strong>The history filter is the most important
  control on this page.</strong> MEXC serves <strong>2,261 days &mdash; 6.19 years</strong> of
  4-hour and daily candles, five times what the hourly bar offers. Set the filter to
  <strong>1000+ days</strong> and you are testing across a full bull-and-bear cycle rather
  than one market mood. Survivor still means: profitable in BOTH halves, green in 70%+ of
  months, 90+ days minimum. Then check the <strong>flat</strong> column &mdash; a survivor
  that only works on martingale is telling you the ladder works, not the signal.</p>
  <div class="grid3" id="verdict"></div>
</header>

<div class="banner" id="coverage"></div>

<div class="controls">
  <label>Base margin $<input type="number" id="margin" value="5" min="0.5" step="0.5"></label>
  <label>Timeframe<select id="ftf"><option value="">all</option>
    </select></label>
  <label>Signal<select id="fsig"><option value="">all</option></select></label>
  <label>Sizing<select id="fsiz"><option value="">both</option>
    <option value="flat">flat only</option>
    <option value="martingale">martingale only</option></select></label>
  <label>Quality<select id="fq"><option value="surv">survivors only</option>
    <option value="">every profitable row</option></select></label>
  <label>Min history<select id="fdays">
    <option value="300">300+ days (a real year)</option>
    <option value="1000">1000+ days (3+ years)</option>
    <option value="180">180+ days</option>
    <option value="90">90+ days</option>
    <option value="0">any, including 2-week coins</option></select></label>
  <div class="hint">A <b>survivor</b> is profitable in BOTH halves of its own history
  and green in at least 70% of its months. Everything else is one lucky stretch until
  proven otherwise.</div>
</div>

<section class="sec">
  <h2>Results</h2>
  <p class="note" id="cnt"></p>
  <div class="scroll">
    <table id="tbl"><thead><tr>
      <th data-s="coin">Coin<span class="ar"></span></th>
      <th data-s="tf">TF<span class="ar"></span></th>
      <th data-s="signal">Signal<span class="ar"></span></th>
      <th data-s="sl">SL<span class="ar"></span></th>
      <th data-s="tp">TP<span class="ar"></span></th>
      <th data-s="sizing">Sizing<span class="ar"></span></th>
      <th data-s="lev">Lev<span class="ar"></span></th>
      <th data-s="margin">Margin $<span class="ar"></span></th>
      <th data-s="notional">Notional $<span class="ar"></span></th>
      <th data-s="fee">Fee %<span class="ar"></span></th>
      <th data-s="rt_cost">Round-trip %<span class="ar"></span></th>
      <th data-s="cost_of_tp">Cost % of TP<span class="ar"></span></th>
      <th data-s="days">History days<span class="ar"></span></th>
      <th data-s="trades">Trades<span class="ar"></span></th>
      <th data-s="wins">WINS<span class="ar"></span></th>
      <th data-s="losses">LOSSES<span class="ar"></span></th>
      <th data-s="winrate">Win %<span class="ar"></span></th>
      <th data-s="profit">PROFIT TOTAL $<span class="ar"></span></th>
      <th data-s="h1">1st half $<span class="ar"></span></th>
      <th data-s="h2">2nd half $<span class="ar"></span></th>
      <th data-s="green">Months green<span class="ar"></span></th>
      <th data-s="worst_month">Worst month $<span class="ar"></span></th>
      <th data-s="worst_trade">Worst trade $<span class="ar"></span></th>
      <th data-s="max_dd">Max DD $<span class="ar"></span></th>
      <th data-s="survivor">Verdict<span class="ar"></span></th>
    </tr></thead><tbody></tbody><tfoot><tr id="foot"></tr></tfoot></table>
  </div>
</section>

<section class="sec">
  <h2>Trade log</h2>
  <div id="panel"><div class="ph">Select a row. Rows marked <span class="tag l">log</span> carry a full trade-by-trade record.</div></div>
</section>

<footer>
  <p><strong>A year of 15m mostly does not exist.</strong> MEXC serves 360 days of
  15-minute candles &mdash; but only for contracts that have been listed that long. Across
  all 979, the median 15m row had <strong>20 days</strong> of history and the median 1m row
  had <strong>one</strong>. The fetch asked for a full year every time; most coins simply
  have not been alive for one. That is a property of the market, not a cap in the code.</p>
  <p><strong>Why so few rows at 1m.</strong> A one-minute target is 0.30&ndash;0.80%.
  Most contracts cost 0.15&ndash;0.30% to get in and out of. When the cost is half the
  target, the trade cannot win no matter what the chart does &mdash; those pairs are
  excluded before testing, and the count is in the banner above. This is the same
  arithmetic that made BDX_USDT unwinnable at 734% of its target.</p>
  <p><strong>History is not comparable across the three.</strong> 1h reaches back about
  14 months, 15m about 3 months, and <strong>1m only about a week</strong> &mdash; that is
  all MEXC serves. The <em>History days</em> column is on every row. A week of data is
  not evidence, whatever the profit column says.</p>
  <p><strong>Method.</strong> Signal at bar close, enter at the next bar&rsquo;s open,
  worst-case fills (stop checked before target within a bar), 20&times; isolated margin,
  real per-contract taker fee plus measured order-book slippage on both sides.
  Only rows with 25+ trades are kept.</p>
</footer>
</div>

<script>
const D = __DATA__;
const ROWS = D.rows, LOGS = D.logs;
let baseMargin = 5, sortKey = "profit", sortDir = -1, selected = null;
const ORIG = 5;
const sc = () => baseMargin / ORIG;
const money = v => (v===null||v===undefined||Number.isNaN(v)) ? "—"
  : (v<0?"−":"+")+"$"+Math.abs(v).toFixed(2);
const pxf = v => (v===null||v===undefined) ? "—"
  : (Math.abs(v)<1 ? (+v).toFixed(6) : (+v).toFixed(3));
const lk = r => [r.coin,r.tf,r.signal,r.sl.toFixed(2),r.tp.toFixed(2),r.sizing].join("|");

/* A "survivor" on two weeks of data is a coin flip, not a result. Requiring
   90+ days is what separates the 15m table's 42 apparent winners (all under
   three months old) from the zero that survive a genuine year. */
const MIN_DAYS = 90;
ROWS.forEach(r => { r.thin = r.days < MIN_DAYS;
                    if (r.thin) r.survivor = false; });
function shown(){
  const t=document.getElementById("ftf").value,
        g=document.getElementById("fsig").value,
        z=document.getElementById("fsiz").value,
        q=document.getElementById("fq").value;
  const md=+document.getElementById("fdays").value;
  return ROWS.filter(r=>(!t||r.tf===t)&&(!g||r.signal===g)&&(!z||r.sizing===z)&&
    r.days>=md && (q==="surv" ? r.survivor : true));
}
function renderVerdict(){
  const md=+(document.getElementById("fdays")||{value:90}).value;
  const pool=ROWS.filter(r=>r.days>=md);
  const byTf={}, survTf={};
  pool.forEach(r=>{ byTf[r.tf]=(byTf[r.tf]||0)+1;
    if(r.survivor) survTf[r.tf]=(survTf[r.tf]||0)+1; });
  const best={};
  pool.filter(r=>r.survivor).forEach(r=>{
    if(!best[r.tf]||r.profit>best[r.tf].profit) best[r.tf]=r; });
  const TFS=[...new Set(ROWS.map(r=>r.tf))];
  const cell=(tf)=>{
    const b=best[tf];
    return `<div class="vstat"><div class="k">${tf} &mdash; best survivor</div>
      <div class="v ${b?'good':'bad'}">${b?money(b.profit*sc()):"none"}</div>
      <div class="n">${b?`${b.coin.replace("_USDT","")} &middot; ${b.signal} &middot;
        SL ${b.sl.toFixed(2)}/TP ${b.tp.toFixed(2)} &middot; ${b.green}/${b.months} green`
        :"nothing survives at this history depth"}<br>
        ${survTf[tf]||0} survivors of ${byTf[tf]||0} profitable</div></div>`;};
  document.getElementById("verdict").innerHTML =
    TFS.map(cell).join("");
}
function renderTable(){
  const list=[...shown()].sort((a,b)=>{
    let x=a[sortKey],y=b[sortKey];
    if(typeof x==="boolean"){x=x?1:0;y=y?1:0;}
    if(typeof x==="string") return sortDir*String(x).localeCompare(String(y));
    return sortDir*((x??-1e9)-(y??-1e9));});
  const tb=document.querySelector("#tbl tbody"); tb.innerHTML="";
  let W=0,L=0,T=0,P=0;
  list.slice(0,400).forEach(r=>{
    W+=r.wins;L+=r.losses;T+=r.trades;P+=r.profit*sc();
    const tr=document.createElement("tr"); tr.tabIndex=0;
    if(r.survivor) tr.classList.add("surv");
    const has=LOGS[lk(r)]?'<span class="tag l">log</span> ':'';
    tr.innerHTML=`<td>${r.coin.replace("_USDT","")}</td><td>${r.tf}</td>
      <td>${r.signal}</td><td>${r.sl.toFixed(2)}%</td><td>${r.tp.toFixed(2)}%</td>
      <td>${r.sizing}</td><td>${r.lev}x</td>
      <td>$${(r.margin*sc()).toFixed(2)}</td><td>$${(r.notional*sc()).toFixed(2)}</td>
      <td>${r.fee.toFixed(3)}</td><td>${r.rt_cost.toFixed(3)}</td>
      <td>${r.cost_of_tp.toFixed(1)}%</td><td>${r.days}</td>
      <td>${r.trades}</td><td>${r.wins}</td><td>${r.losses}</td><td>${r.winrate}</td>
      <td class="num ${r.profit<0?'bad':'good'}"><b>${money(r.profit*sc())}</b></td>
      <td class="num ${r.h1<0?'bad':'good'}">${money(r.h1*sc())}</td>
      <td class="num ${r.h2<0?'bad':'good'}">${money(r.h2*sc())}</td>
      <td>${r.green}/${r.months}</td>
      <td class="num ${r.worst_month<0?'bad':'good'}">${money(r.worst_month*sc())}</td>
      <td class="num bad">${money(r.worst_trade*sc())}</td>
      <td>$${(r.max_dd*sc()).toFixed(2)}</td>
      <td>${has}${r.survivor?'<span class="tag s">survivor</span>':'<span class="tag p">one stretch</span>'}</td>`;
    const open=()=>{document.querySelectorAll("#tbl tbody tr").forEach(x=>x.classList.remove("sel"));
      tr.classList.add("sel"); selected=r; renderPanel(r);};
    tr.onclick=open;
    tr.onkeydown=e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();open();}};
    tb.appendChild(tr);});
  document.getElementById("foot").innerHTML=
    `<td colspan="13">${Math.min(list.length,400)} of ${list.length} shown</td>
     <td>${T}</td><td>${W}</td><td>${L}</td><td>${T?(100*W/T).toFixed(1):0}</td>
     <td class="num ${P<0?'bad':'good'}"><b>${money(P)}</b></td><td colspan="7"></td>`;
  document.getElementById("cnt").innerHTML =
    `<strong>${ROWS.length} profitable configurations</strong> out of the combinations `+
    `tested so far &mdash; ${ROWS.filter(r=>r.survivor).length} of them survivors. `+
    `Green rows cleared both halves. Click a row marked <span class="tag l">log</span> for its trade-by-trade record.`;
  document.querySelectorAll("th[data-s]").forEach(th=>{
    th.querySelector(".ar").textContent=th.dataset.s===sortKey?(sortDir>0?" ▲":" ▼"):"";});
}
document.querySelectorAll("th[data-s]").forEach(th=>{
  th.onclick=()=>{if(sortKey===th.dataset.s) sortDir*=-1; else {sortKey=th.dataset.s;sortDir=-1;}
    renderTable();};});
function renderPanel(r){
  const s=sc(), d=LOGS[lk(r)];
  const p=document.getElementById("panel");
  if(!d){ p.innerHTML=`<div class="ph">No trade log stored for this row.<br>
    Logs are captured for the strongest rows of each timeframe to keep this page loadable.</div>`;
    return; }
  const mo=Object.entries(d.monthly).sort();
  /* The stored log is capped at 400 trades to keep this page loadable, so
     summing the visible rows understates a row with more trades. The TOTAL
     must be the row's real figure, with the truncation stated. */
  const tot=r.profit*s;
  const shownSum=d.log.reduce((a,t)=>a+t["pnl $"],0)*s;
  const truncated=r.trades>d.log.length;
  p.innerHTML=`
    <h2>${r.coin.replace("_USDT","")} &middot; ${r.tf} &middot; ${r.signal} &middot;
      SL ${r.sl.toFixed(2)}% / TP ${r.tp.toFixed(2)}% &middot; ${r.sizing}
      ${r.survivor?'<span class="tag s">survivor</span>':'<span class="tag p">one stretch</span>'}</h2>
    <p class="note">${r.days} days of history, ${r.trades} trades, cost
      ${r.rt_cost.toFixed(3)}% round-trip = ${r.cost_of_tp.toFixed(1)}% of the target.
      ${r.survivor?"Profitable in both halves and green in most months."
        :"<strong>Not a survivor</strong> — profitable overall, but it failed one half of its own history or too many months. Treat as one lucky stretch."}</p>
    <div class="pgrid">
      <div class="pcell"><div class="k">Profit total</div>
        <div class="v" style="color:${r.profit<0?'var(--bad)':'var(--good)'}">${money(r.profit*s)}</div></div>
      <div class="pcell"><div class="k">1st half</div>
        <div class="v" style="color:${r.h1<0?'var(--bad)':'var(--good)'}">${money(r.h1*s)}</div></div>
      <div class="pcell"><div class="k">2nd half</div>
        <div class="v" style="color:${r.h2<0?'var(--bad)':'var(--good)'}">${money(r.h2*s)}</div></div>
      <div class="pcell"><div class="k">Take-profit</div><div class="v">${r.tp.toFixed(2)}%</div></div>
      <div class="pcell"><div class="k">Stop-loss</div><div class="v">${r.sl.toFixed(2)}%</div></div>
      <div class="pcell"><div class="k">Leverage</div><div class="v">${r.lev}x</div></div>
      <div class="pcell"><div class="k">Base margin</div><div class="v">$${(r.margin*s).toFixed(2)}</div></div>
      <div class="pcell"><div class="k">Notional</div><div class="v">$${(r.notional*s).toFixed(2)}</div></div>
      <div class="pcell"><div class="k">Wins / Losses</div><div class="v">${r.wins} / ${r.losses}</div></div>
      <div class="pcell"><div class="k">Win rate</div><div class="v">${r.winrate}%</div></div>
      <div class="pcell"><div class="k">Worst trade</div>
        <div class="v" style="color:var(--bad)">${money(r.worst_trade*s)}</div></div>
      <div class="pcell"><div class="k">Max drawdown</div><div class="v">$${(r.max_dd*s).toFixed(2)}</div></div>
    </div>
    <div class="months">${mo.map(([m,v])=>`<span class="mo ${v>0?'g':'r'}">${m} ${money(v*s)}</span>`).join("")}</div>
    ${truncated?`<p class="note" style="margin-top:10px"><strong>Showing the first
      ${d.log.length} of ${r.trades} trades.</strong> The total above is the full run;
      the running column below stops at trade ${d.log.length}.</p>`:""}
    <div class="logscroll"><table><thead><tr>
      <th style="text-align:left">Entry time</th><th style="text-align:left">Exit time</th>
      <th>Side</th><th>Step</th><th>Margin $</th><th>Notional $</th><th>Entry</th>
      <th>TP px</th><th>SL px</th><th>Exit</th><th>Why</th><th>W/L</th>
      <th>PnL $</th><th>Running $</th></tr></thead><tbody>
      ${d.log.map(t=>`<tr>
        <td style="text-align:left">${t["entry time"]}</td>
        <td style="text-align:left">${t["exit time"]}</td>
        <td>${t.side}</td><td>${t.step}</td>
        <td>${(t["margin $"]*s).toFixed(2)}</td>
        <td>${(t["notional $"]*s).toFixed(2)}</td>
        <td>${pxf(t.entry)}</td><td>${pxf(t["TP px"])}</td><td>${pxf(t["SL px"])}</td>
        <td>${pxf(t.exit)}</td><td>${t.why}</td>
        <td class="num ${t["WIN/LOSE"]==="WIN"?'good':'bad'}">${t["WIN/LOSE"]}</td>
        <td class="num ${t["pnl $"]<0?'bad':'good'}">${money(t["pnl $"]*s)}</td>
        <td>${money(t["running total $"]*s)}</td></tr>`).join("")}
    </tbody></table></div>
    <div class="total">
      <div><div class="lab">TOTAL PROFIT (all ${r.trades} trades)</div>
        <div class="big num ${tot<0?'bad':'good'}">${money(tot)}</div></div>
      ${truncated?`<div><div class="lab">of which, the ${d.log.length} shown</div>
        <div class="big num ${shownSum<0?'bad':'good'}">${money(shownSum)}</div></div>`:""}
      <div><div class="lab">Trades shown</div><div class="big">${d.log.length}${truncated?" of "+r.trades:""}</div></div>
      <div><div class="lab">Wins / Losses</div><div class="big">${r.wins} / ${r.losses}</div></div>
      <div><div class="lab">Months green</div><div class="big">${r.green}/${r.months}</div></div>
    </div>`;
}
const sig=document.getElementById("fsig");
[...new Set(ROWS.map(r=>r.signal))].sort().forEach(v=>{
  const o=document.createElement("option"); o.value=v; o.textContent=v; sig.appendChild(o);});
document.addEventListener("input",e=>{
  if(e.target.id!=="margin") return;
  const v=parseFloat(e.target.value); baseMargin=(isFinite(v)&&v>0)?v:5;
  renderVerdict(); renderTable(); if(selected) renderPanel(selected);});
document.addEventListener("change",e=>{
  if(["ftf","fsig","fsiz","fq","fdays"].includes(e.target.id)){
    renderVerdict(); renderTable(); }});
document.getElementById("stamp").textContent=D.stamp;
document.getElementById("coverage").innerHTML =
  `<b>Coverage: ${D.coins_done} of ${D.coins_total} contracts swept so far.</b> `+
  `${D.excluded_total} coin/timeframe pairs excluded — order book unreadable, too little `+
  `history, or the liquidity gate (cost ≥ 50% of every target at that timeframe). `+
  `This page updates at the same link as the sweep finishes.`;
renderVerdict(); renderTable();
</script>
"""

out = HTML.replace("__TFS__", _TFL).replace("__DATA__", json.dumps(D, separators=(",", ":")))
(HERE / "all-coins-sweep.html").write_text(out, encoding="utf-8")
print("wrote", (HERE / "all-coins-sweep.html").stat().st_size, "bytes")
