import { chromium } from 'playwright';
const api = async (p) => (await fetch('http://localhost:8787' + p)).json();
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1680, height: 1050 } });
const errors = [];
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));

await page.goto('http://localhost:3000/backtest', { waitUntil: 'networkidle' });
await page.waitForTimeout(3000);
const fails = [];
const ok = (n, c, d) => { console.log((c ? 'PASS ' : 'FAIL ') + n + (d ? ' — ' + d : '')); if (!c) fails.push(n); };
const body = await page.evaluate(() => document.body.innerText);

// 1. unfiltered total equals the store
const strat = await api('/api/strategies?limit=1');
ok('strategies total', body.includes(strat.total.toLocaleString('en-US')), `api=${strat.total}`);
ok('losers included lede', body.includes('losers included'));

// 2. storage caption total ≈ API sum (download job is growing the store, allow 5 MB drift)
const st = await api('/api/storage/by-coin');
const apiSum = st.rows.reduce((a, r) => a + r.total, 0) / 1e6;
const m = body.match(/([\d.]+) MB total/);
ok('storage TOTAL caption', !!m && Math.abs(parseFloat(m[1]) - apiSum) < 5, `page=${m?.[1]} api=${apiSum.toFixed(2)}`);

// 3. mandatory columns present in strategies header
for (const col of ['coin', 'lev', 'margin $', 'PROFIT $', 'SL%', 'TP%', 'W', 'L', 'trades'])
  ok(`column ${col}`, body.includes(col));

// 4. click top strategy row -> viewer opens; poll to 30s for badges
await page.locator('table tbody tr').filter({ hasText: /#/ }).first().click();
let opened = false, body2 = '';
for (let i = 0; i < 15; i++) {
  await page.waitForTimeout(2000);
  body2 = await page.evaluate(() => document.body.innerText);
  if (/\d+ trades/.test(body2) && /TOTAL [+-]/.test(body2)) { opened = true; break; }
}
ok('trade viewer badges', opened);

// 5. viewer badges reconcile with the API's own rebuild of the same row
const top = (await api('/api/strategies?limit=1')).rows[0];
const tr = await (await fetch('http://localhost:8787/api/strategies/trades', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ coin: top.coin, tf: top.tf, signal: top.signal, th: top.th ?? 0, sl: top.sl, tp: top.tp, sizing: top.sizing, base_margin: 5.0 }) })).json();
if (tr.log?.length) {
  const sum = tr.log.reduce((a, r) => a + (r['pnl $'] || 0), 0);
  ok('log sums to profit (1c/row tolerance)', Math.abs(sum - tr.profit) <= 0.01 * tr.log.length, `sum=${sum.toFixed(2)} profit=${tr.profit}`);
  ok('badge trade count', body2.includes(`${tr.trades} trades`), `${tr.trades}`);
  ok('badge W/L', body2.includes(`${tr.wins} WIN`) && body2.includes(`${tr.losses} LOSE`), `${tr.wins}W/${tr.losses}L`);
}
await page.screenshot({ path: '/tmp/react-backtest2.png', fullPage: false });
console.log('js errors:', errors.length ? errors.slice(0, 3) : 'none');
console.log(fails.length ? 'RESULT: FAIL ' + fails.join(', ') : 'RESULT: ALL PASS');
await browser.close();
