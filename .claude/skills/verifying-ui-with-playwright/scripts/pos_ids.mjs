import { chromium } from 'playwright';
const api = async (p) => (await fetch('http://localhost:8503' + p)).json();
const b = await chromium.launch();
const page = await b.newPage({ viewport: { width: 1600, height: 1200 } });
const errors = []; page.on('pageerror', e => errors.push(e.message));
page.on('dialog', d => d.dismiss());
await page.goto('http://localhost:8503/trade', { waitUntil: 'domcontentloaded' });
await page.waitForSelector('text=Positions', { timeout: 60000 });
await page.waitForTimeout(6000);
const fails = []; const ok = (n,c,d) => { console.log((c?'PASS ':'FAIL ')+n+(d?' — '+d:'')); if(!c) fails.push(n); };
const body = await page.evaluate(() => document.body.innerText);
const p = await api('/api/trade/positions');
const grid = await api('/api/trade/strategies');

const rows = [...p.real, ...p.paper];
ok('there are positions to check', rows.length > 0, `${rows.length}`);
for (const r of rows) {
  ok(`${r.coin} id on screen`, r.id ? body.includes(`#${r.id}`) : true, `#${r.id}`);
  const g = grid.rows.find((x) => x.key === r.strategy);
  if (g) ok(`${r.coin} id matches the grid's`, r.id === g.id, `${r.id} vs ${g.id}`);
}
// the id sits in the contract cell, with the coin and the strategy
const cells = await page.evaluate(() => {
  const t = [...document.querySelectorAll('table')].find(t => t.textContent.includes('to TP'));
  return [...t.querySelectorAll('tbody tr td:first-child')].map(td => td.innerText.trim());
});
ok('id is in the contract column', cells.some((c) => /#[A-Z0-9]{8}/.test(c)), cells[0]?.replace(/\n/g, " | "));
ok('coin still first in the cell', /^[A-Z0-9]+\n#/.test(cells[0] ?? ""), cells[0]?.split("\n")[0]);
// clicking it copies
await page.context().grantPermissions(['clipboard-write', 'clipboard-read']).catch(() => {});
const idBtn = page.locator('td button[title="copy this id"]').first();
ok('the id is clickable to copy', await idBtn.count() > 0);
ok('no js errors', errors.length === 0, errors[0] ?? '');
await page.screenshot({ path: '/tmp/pos-ids.png', fullPage: false });
console.log(fails.length ? 'RESULT: FAIL ' + fails.join(', ') : 'RESULT: ALL PASS');
await b.close();
