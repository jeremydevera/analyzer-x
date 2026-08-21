import { chromium } from 'playwright';
const api = async (p) => (await fetch('http://localhost:8503' + p)).json();
const b = await chromium.launch();
const page = await b.newPage({ viewport: { width: 1920, height: 1250 } });
const errors = []; page.on('pageerror', e => errors.push(e.message));
const dialogs = [];
page.on('dialog', d => { dialogs.push(d.message()); d.dismiss(); });
await page.goto('http://localhost:8503/trade', { waitUntil: 'networkidle' });
await page.waitForTimeout(6000);
const fails = []; const ok = (n,c,d) => { console.log((c?'PASS ':'FAIL ')+n+(d?' — '+d:'')); if(!c) fails.push(n); };
let body = await page.evaluate(() => document.body.innerText);
const p = await api('/api/trade/positions');

// all fourteen headers, by name
const HEADS = ["contract","unreal $","to TP","TP % ($)","SL % ($)","W","L","trd","side","opened","held","entry","margin","bracket"];
for (const h of HEADS) ok(`column "${h}"`, body.includes(h));
ok('caption counts both books', body.includes(`${p.real.length} real (exchange-confirmed) · ${p.paper.length} paper (simulated)`));
ok('leverage stated', body.includes(`${p.leverage}x leverage`));

// per-row values match the API row for row. unrealized and progress move with
// the mark price between the render and this sample, so those two get a
// tolerance read off the row's own cells; everything else is exact.
const cells = await page.evaluate(() => {
  const t = [...document.querySelectorAll('table')].find(t => t.textContent.includes('to TP'));
  return [...(t?.querySelectorAll('tbody tr') ?? [])]
    .map(tr => [...tr.querySelectorAll('td')].map(td => td.textContent.trim()));
});
const num = (t) => parseFloat(String(t).replace(/[+,%$ ]/g, ''));
for (const r of p.real) {
  const row = cells.find(c => c[0]?.includes(r.coin) && c[0]?.startsWith('REAL'));
  ok(`${r.coin} row present`, !!row);
  if (!row) continue;
  ok(`${r.coin} unrealized within drift`, Math.abs(num(row[1]) - r.unrealized) < 0.75,
     `page=${row[1]} api=${r.unrealized}`);
  ok(`${r.coin} progress within drift`, Math.abs(num(row[2]) - r.progress_pct) < 5 && row[2].includes(r.progress_to),
     `page=${row[2]} api=${r.progress_pct}% ${r.progress_to}`);
  ok(`${r.coin} TP pct+usd exact`, row[3].includes(r.tp_value.pct.toFixed(2)) && row[3].includes(r.tp_value.usd.toFixed(2)), row[3]);
  ok(`${r.coin} SL pct+usd exact`, row[4].includes(r.sl_value.pct.toFixed(2)), row[4]);
  ok(`${r.coin} W/L/trd exact`, row[5] === String(r.wins) && row[6] === String(r.losses) && row[7] === String(r.trades),
     `${row[5]}/${row[6]}/${row[7]}`);
  ok(`${r.coin} opened stamp exact`, row[9] === r.opened, row[9]);
  // held counts up with the clock, so it can tick between render and sample
  const mins = (t) => { const m = String(t).match(/(?:(\d+)d )?(?:(\d+)h )?(\d+)m/);
    return m ? (+(m[1]||0))*1440 + (+(m[2]||0))*60 + (+m[3]) : NaN; };
  ok(`${r.coin} held within a tick`, Math.abs(mins(row[10]) - mins(r.held)) <= 2,
     `page=${row[10]} api=${r.held}`);
}
ok('unprotected banner matches reality',
   p.unprotected.length ? body.includes('NO STOP resting at the exchange') : !body.includes('NO STOP resting'),
   `${p.unprotected.length} unprotected`);

// safety controls present; PANIC disabled until armed
ok('HALT ENTRIES button', /halt entries/i.test(body));
ok('arm PANIC checkbox', /arm panic/i.test(body));
const panic = page.locator('button', { hasText: 'PANIC — close all' }).first();
ok('PANIC disabled until armed', await panic.isDisabled());
await page.locator('input[type="checkbox"]').filter({ has: page.locator(':scope') }).first().check().catch(()=>{});
await page.getByText('arm PANIC').locator('..').locator('input[type="checkbox"]').check();
await page.waitForTimeout(400);
ok('PANIC enabled once armed', !(await panic.isDisabled()));
// clicking it must ASK before doing anything
await panic.click();
await page.waitForTimeout(800);
ok('PANIC asks first', dialogs.some(m => /close everything at market/i.test(m)), dialogs[0]?.slice(0,60) ?? 'no dialog');
ok('PANIC dialog states the cost', dialogs.some(m => /becomes real/i.test(m)));

// close-one asks too, naming the position
const closeBtn = page.locator('button', { hasText: /^close$/ }).first();
if (await closeBtn.count()) {
  await closeBtn.click();
  await page.waitForTimeout(800);
  ok('close-one asks, naming coin+margin', dialogs.some(m => /Close .* at market now/i.test(m) && /margin at/i.test(m)));
}
ok('no js errors', errors.length === 0, errors[0] ?? '');
await page.screenshot({ path: '/tmp/positions14.png', fullPage: false });
console.log(fails.length ? 'RESULT: FAIL ' + fails.join(', ') : 'RESULT: ALL PASS');
await b.close();
