import { chromium } from 'playwright';
const api = async (p) => (await fetch('http://localhost:8503' + p)).json();
const b = await chromium.launch();
const page = await b.newPage({ viewport: { width: 1512, height: 1200 } });
const errors = []; page.on('pageerror', e => errors.push(e.message));
const dialogs = []; page.on('dialog', d => { dialogs.push(d.message()); d.dismiss(); });
// this screen polls, so networkidle never settles — wait for the content
await page.goto('http://localhost:8503/candles', { waitUntil: 'domcontentloaded' });
await page.waitForSelector('text=UPDATE CANDLES', { timeout: 60000 });
await page.waitForFunction(() => /pair\(s\) stored/.test(document.body.innerText), { timeout: 60000 });
await page.waitForTimeout(2500);
const fails = []; const ok = (n,c,d) => { console.log((c?'PASS ':'FAIL ')+n+(d?' — '+d:'')); if(!c) fails.push(n); };
let body = await page.evaluate(() => document.body.innerText);
const gaps = await api('/api/candles/gaps');
const st = await api('/api/storage/by-coin');

// --- UPDATE CANDLES
ok('UPDATE CANDLES button', body.includes('UPDATE CANDLES'));
ok('gap readout from the store', body.includes(`${gaps.pairs.toLocaleString('en-US')} pair(s) stored`), String(gaps.pairs));
ok('says how many are behind', gaps.behind ? body.includes(`${gaps.behind}`) && body.includes('behind by more than a bar') : body.includes('all up to date'));
ok('names the furthest-behind pair', !gaps.worst || body.includes(gaps.worst.symbol.replace('_USDT','')), gaps.worst?.symbol);
ok('says it fills exactly those gaps', body.includes('fills exactly those gaps'));
ok('UPDATE needs no coin selection', !(await page.locator('button', { hasText: 'UPDATE CANDLES' }).first().isDisabled()));
ok('DOWNLOAD still needs a coin', await page.locator('button', { hasText: 'DOWNLOAD CANDLES' }).first().isDisabled());
await page.locator('button', { hasText: 'UPDATE CANDLES' }).first().click();
await page.waitForTimeout(900);
ok('UPDATE asks first and explains', dialogs.some(m => /Update \d+ stored pair/.test(m) && /nothing is downloaded again/.test(m)),
   dialogs[0]?.slice(0, 60));

// --- size per coin: timeframes + pagination
const coins = new Set(st.rows.map(r => r.coin));
ok('per-coin caption counts coins and pages', /\d+ coins · page 1 of \d+/.test(body), body.match(/\d+ coins · page 1 of \d+/)?.[0]);
ok('header says timeframes downloaded', body.includes('timeframes downloaded'));
const firstCoin = [...st.rows].sort((a,b) => b.total - a.total)[0].coin;
const tfsOfFirst = st.rows.filter(r => r.coin === firstCoin).map(r => r.tf);
ok('timeframe names shown, not a count', tfsOfFirst.every(t => body.includes(t)), `${firstCoin}: ${tfsOfFirst.join(",")}`);
const rowsShown = await page.evaluate(() => {
  const t = [...document.querySelectorAll('table')].find(t => t.textContent.includes('timeframes downloaded'));
  return t ? t.querySelectorAll('tbody tr').length : 0;
});
ok('page holds 15 rows, not all of them', rowsShown === 15 && coins.size > 15, `${rowsShown} of ${coins.size} coins`);
const before = await page.evaluate(() => {
  const t = [...document.querySelectorAll('table')].find(t => t.textContent.includes('timeframes downloaded'));
  return t.querySelector('tbody tr td').textContent.trim();
});
await page.locator('button', { hasText: /^2$/ }).first().click();
await page.waitForTimeout(900);
const after = await page.evaluate(() => {
  const t = [...document.querySelectorAll('table')].find(t => t.textContent.includes('timeframes downloaded'));
  return t.querySelector('tbody tr td').textContent.trim();
});
ok('page 2 shows different coins', before !== after, `${before} → ${after}`);
body = await page.evaluate(() => document.body.innerText);
ok('caption follows the page', /page 2 of \d+/.test(body));
ok('no js errors', errors.length === 0, errors[0] ?? '');
await page.screenshot({ path: '/tmp/candles.png', fullPage: false });
console.log(fails.length ? 'RESULT: FAIL ' + fails.join(', ') : 'RESULT: ALL PASS');
await b.close();
