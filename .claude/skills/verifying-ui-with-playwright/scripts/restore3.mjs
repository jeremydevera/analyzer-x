import { chromium } from 'playwright';
const api = async (p) => (await fetch('http://localhost:8503' + p)).json();
const b = await chromium.launch();
const page = await b.newPage({ viewport: { width: 1920, height: 1300 } });
const errors = []; page.on('pageerror', e => errors.push(e.message));
page.on('dialog', d => d.dismiss());
const fails = []; const ok = (n,c,d) => { console.log((c?'PASS ':'FAIL ')+n+(d?' — '+d:'')); if(!c) fails.push(n); };

// ---------- 1. the two books are SEPARATE
await page.goto('http://localhost:8503/trade', { waitUntil: 'networkidle' });
await page.waitForTimeout(6500);
let body = await page.evaluate(() => document.body.innerText);
const p = await api('/api/trade/positions');
ok('REAL box has its own badge', body.includes('REAL — MONEY AT RISK'));
ok('PAPER box has its own badge', body.includes('PAPER — DEMO, NOT REAL MONEY'));
ok('each box counts its own rows', body.includes(`REAL — MONEY AT RISK· ${p.real.length} open`) || body.includes(`${p.real.length} open`));
const tables = await page.evaluate(() => [...document.querySelectorAll('table')]
  .filter(t => t.textContent.includes('to TP')).length);
ok('two position tables, not one', tables === 2, `${tables} tables`);
// no row can be ambiguous: every real row sits under the REAL badge
const layout = await page.evaluate(() => {
  const out = [];
  document.querySelectorAll('table').forEach((t) => {
    if (!t.textContent.includes('to TP')) return;
    let n = t, label = '';
    for (let i = 0; i < 6 && n; i++) {
      n = n.parentElement;
      const f = n?.firstElementChild?.textContent?.trim() ?? '';
      if (/REAL — MONEY|PAPER — DEMO/.test(f)) { label = f; break; }
    }
    // the coin is the FIRST span of the cell; the strategy is a sibling span
    // and textContent would glue them into "PItrend50_30m_pi"
    out.push({ label, coins: [...t.querySelectorAll('tbody tr td:first-child span:first-child')]
      .map(sp => sp.textContent.trim()) });
  });
  return out;
});
ok('real coins only in the REAL box',
   layout[0]?.coins.every(c => p.real.some(r => r.coin === c)), JSON.stringify(layout[0]?.coins));
ok('paper coins only in the PAPER box',
   layout[1]?.coins.every(c => p.paper.some(r => r.coin === c)), JSON.stringify(layout[1]?.coins));

// ---------- 2. trade history, both books, months, pagination
const live = await api('/api/trade/history?dry=false&page=1');
ok('history section present', body.includes('Trade history') && body.includes('every closed trade'));
ok('LIVE/DEMO tabs', body.includes('LIVE — real money') && body.includes('DEMO — simulated'));
ok('history count from the API', body.includes(`${live.total} on this book`), String(live.total));
// innerText returns the RENDERED case and this heading is uppercase in CSS
ok('per-month summary', /profit per month/i.test(body) && body.includes(live.months[0].label),
   live.months[0].label);
ok('month totals row', body.includes('TOTAL'));
ok('first page row shown', body.includes(live.rows[0].when) && body.includes(live.rows[0].strategy));
ok('running total column', body.includes('running $'));
ok('pager present', body.includes(`page 1 of ${live.pages}`), `${live.pages} pages`);
// page 2 must show page 2's rows, with the book-wide running total
await page.locator('button', { hasText: /^2$/ }).first().click();
await page.waitForTimeout(1800);
body = await page.evaluate(() => document.body.innerText);
const p2 = await api('/api/trade/history?dry=false&page=2');
ok('page 2 loads its own rows', body.includes(p2.rows[0].when), p2.rows[0].when);
ok('page 2 keeps the book-wide running total', body.includes(String(p2.rows[0].running.toFixed(2))));
// the DEMO tab is a different book
await page.locator('button', { hasText: 'DEMO — simulated' }).first().click();
await page.waitForTimeout(1800);
body = await page.evaluate(() => document.body.innerText);
const demo = await api('/api/trade/history?dry=true&page=1');
ok('demo tab shows the demo book', body.includes(`${demo.total} on this book`), `${demo.total} vs live ${live.total}`);
ok('demo totals differ from live', demo.totals.profit !== live.totals.profit);

// ---------- 3. the coin picker
await page.goto('http://localhost:8503/backtest', { waitUntil: 'networkidle' });
await page.waitForTimeout(4000);
body = await page.evaluate(() => document.body.innerText);
const cts = await api('/api/contracts');
ok('picker says none selected, of the real total',
   body.includes(`none of ${cts.rows.length.toLocaleString('en-US')} coins selected`), String(cts.rows.length));
// the placeholder changes to "add another…" once a chip exists, so address
// the input by its container instead of its text
const picker = page.locator('div').filter({ hasText: /coins selected/ }).last();
const search = page.locator('input[placeholder="search contracts…"], input[placeholder="add another…"]').first();
ok('search box, not a free-text symbol field', await search.count() === 1);
await search.click();
await page.waitForTimeout(500);
await search.fill('XAUT');
await page.waitForTimeout(600);
await page.locator('button', { hasText: /^XAUT/ }).first().click();
await page.waitForTimeout(500);
await search.fill('APEX');
await page.waitForTimeout(600);
await page.locator('button', { hasText: /^APEX/ }).first().click();
await page.waitForTimeout(1500);
body = await page.evaluate(() => document.body.innerText);
ok('selected count updates', body.includes(`2 of ${cts.rows.length.toLocaleString('en-US')} coins selected`));
ok('chips show the picks', body.includes('XAUT') && body.includes('APEX'));
ok('plan follows the picks', /2 coin\(s\)/.test(body));
ok('no js errors', errors.length === 0, errors[0] ?? '');
await page.screenshot({ path: '/tmp/restore3-backtest.png', fullPage: false });
await page.goto('http://localhost:8503/trade', { waitUntil: 'networkidle' });
await page.waitForTimeout(5000);
await page.screenshot({ path: '/tmp/restore3-trade.png', fullPage: false });
console.log(fails.length ? 'RESULT: FAIL ' + fails.join(', ') : 'RESULT: ALL PASS');
await b.close();
