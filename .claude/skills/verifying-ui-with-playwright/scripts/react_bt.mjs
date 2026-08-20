import { chromium } from 'playwright';

const api = async (p) => (await fetch('http://localhost:8787' + p)).json();

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1680, height: 1050 } });
const errors = [];
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

await page.goto('http://localhost:3000/backtest', { waitUntil: 'networkidle' });
await page.waitForTimeout(3000);

const fails = [];
const ok = (name, cond, detail) => { console.log((cond ? 'PASS ' : 'FAIL ') + name + (detail ? ' — ' + detail : '')); if (!cond) fails.push(name); };

// 1. stored strategies total: page count line vs API
const strat = await api('/api/strategies?limit=1');
const body = await page.evaluate(() => document.body.innerText);
ok('strategies total on page', body.includes(strat.total.toLocaleString('en-US')) || body.includes(String(strat.total)),
   `api total=${strat.total}`);

// 2. size-per-coin: every coin row total matches API, and the sum line
const st = await api('/api/storage/by-coin');
const sumMB = (st.rows.reduce((a, r) => a + r.total, 0) / 1e6).toFixed(2);
ok('storage sum on page', body.includes(sumMB + ' MB'), `api sum=${sumMB} MB, rows=${st.rows.length}`);
const first = st.rows[0];
ok('first coin row', body.includes((first.total / 1e6).toFixed(2) + ' MB'), `${first.coin} ${(first.total/1e6).toFixed(2)} MB`);

// 3. coverage rows present
const cov = await api('/api/storage/coverage');
if (cov.rows.length) {
  const c = cov.rows[0];
  ok('coverage row bars', body.includes(c.bars.toLocaleString('en-US')) || body.includes(String(c.bars)), `${c.symbol} ${c.timeframe} bars=${c.bars}`);
}

// 4. click first strategy row -> trade viewer opens, badges reconcile with API trades
const rowSel = 'table tbody tr';
const stratTable = page.locator('h3:has-text("Stored strategies")').locator('..').locator('table').last();
await page.locator('#strategies table tbody tr, [data-panel="strategies"] table tbody tr').first().click().catch(async () => {
  // fallback: click the first row in the strategies panel by finding a mono id cell
  await page.locator('td:has-text("#")').first().click();
});
await page.waitForTimeout(4000);
const body2 = await page.evaluate(() => document.body.innerText);
const opened = /PAST TRADES|trades ·|WIN/.test(body2);
ok('trade viewer opened on row click', opened);

// pull the exact top strategy the page shows (API default sort) and reconcile
const topQ = await api('/api/strategies?limit=1');
const top = topQ.rows[0];
const tr = await (await fetch('http://localhost:8787/api/strategies/trades', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ coin: top.coin, tf: top.tf, signal: top.signal, th: top.th ?? 0, sl: top.sl, tp: top.tp, sizing: top.sizing, base_margin: 5.0 }),
})).json();
if (tr.log) {
  const sum = tr.log.reduce((a, r) => a + (r['pnl $'] || 0), 0);
  ok('api trade log sums to its own profit', Math.abs(sum - (tr.profit ?? sum)) < 0.05, `sum=${sum.toFixed(2)} profit=${tr.profit}`);
  const badge = body2.includes(String(tr.log.length)) ;
  ok('trade count visible after click', badge, `log rows=${tr.log.length}`);
}

// 5. jobs panel controls exist
ok('DOWNLOAD button', body.includes('DOWNLOAD CANDLES'));
ok('BACKTEST button', /BACKTEST/.test(body));

await page.screenshot({ path: '/tmp/react-backtest.png', fullPage: true });
console.log('js errors:', errors.length ? errors.slice(0, 5) : 'none');
console.log(fails.length ? 'RESULT: FAIL ' + fails.join(', ') : 'RESULT: ALL PASS');
await browser.close();
