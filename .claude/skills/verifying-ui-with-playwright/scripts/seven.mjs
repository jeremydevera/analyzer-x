import { chromium } from 'playwright';
const api = async (p) => (await fetch('http://localhost:8503' + p)).json();
const b = await chromium.launch();
const fails = []; const ok = (n,c,d) => { console.log((c?'PASS ':'FAIL ')+n+(d?' — '+d:'')); if(!c) fails.push(n); };
const page = await b.newPage({ viewport: { width: 1512, height: 1100 } });
const errors = []; page.on('pageerror', e => errors.push(e.message));
page.on('dialog', d => d.dismiss());

// ---- 2 & 3: Candles is its own screen; Backtest is backtest only
await page.goto('http://localhost:8503/candles', { waitUntil: 'networkidle' });
await page.waitForTimeout(4500);
let body = await page.evaluate(() => document.body.innerText);
ok('Candles screen exists', body.includes('Download candles'));
ok('download button lives there', body.includes('DOWNLOAD CANDLES'));
ok('storage moved with it', body.includes('Size per coin') && body.includes('Candles on this Mac'));
ok('nav lists Candles', (await page.locator('nav a[href="/candles"]').count()) === 1);

// ---- 1: select all
const search = page.locator('input[placeholder="search contracts…"]').first();
const cts = await api('/api/contracts');
ok('select-all button', body.includes(`select all ${cts.rows.length.toLocaleString('en-US')}`), String(cts.rows.length));
await page.locator('button', { hasText: /^select all/ }).first().click();
await page.waitForTimeout(1200);
body = await page.evaluate(() => document.body.innerText);
ok('select all picks every contract',
   body.includes(`${cts.rows.length.toLocaleString('en-US')} of ${cts.rows.length.toLocaleString('en-US')} coins selected`));
await page.locator('button', { hasText: /^clear$/ }).first().click();
await page.waitForTimeout(700);
// select-all-of-a-filter
await search.fill('1000');
await page.waitForTimeout(800);
body = await page.evaluate(() => document.body.innerText);
ok('select all matching a search', /select all \d+ matching/.test(body), body.match(/select all \d+ matching[^\n]*/)?.[0]);

await page.goto('http://localhost:8503/backtest', { waitUntil: 'networkidle' });
await page.waitForTimeout(4000);
body = await page.evaluate(() => document.body.innerText);
ok('Backtest has no download control', !body.includes('DOWNLOAD CANDLES'));
ok('Backtest still runs backtests', body.includes('BACKTEST') && body.includes('UPDATE BACKTEST'));
ok('Backtest points at the Candles screen', body.includes('Candles'));
ok('storage panels left the Backtest screen', !body.includes('Size per coin'));

// ---- 4, 5, 7 on Auto Trade
await page.goto('http://localhost:8503/trade', { waitUntil: 'networkidle' });
await page.waitForTimeout(6000);
body = await page.evaluate(() => document.body.innerText);
ok('equity section gone', !body.includes('Equity, every closed trade'));
ok('per-month block gone from history', !/profit per month/i.test(body));
ok('history itself still there', body.includes('Trade history') && body.includes('running $'));
const st = await api('/api/trade/strategies');
const coinInputs = await page.evaluate(() => {
  const tr = [...document.querySelectorAll('tr')].filter(r => /^(mom|fvg|sweep|trend|fade|ict|rsi)/.test(r.textContent.trim()));
  return tr.map(r => [...r.querySelectorAll('input')].length);
});
ok('coins are read-only text, not inputs',
   coinInputs.every((n) => n === 2), `inputs per row: ${[...new Set(coinInputs)].join(",")} (margin + loss cap only)`);
const shown = st.rows[0].coins.map((c) => c.replace('_USDT','')).join(', ');
ok('the coin is still printed', body.includes(shown), shown);
ok('W / L merged into one column', body.includes('W / L'));
ok('no js errors', errors.length === 0, errors[0] ?? '');
await page.screenshot({ path: '/tmp/seven-trade.png', fullPage: false });
console.log(fails.length ? 'RESULT: FAIL ' + fails.join(', ') : 'RESULT: ALL PASS');
await b.close();
