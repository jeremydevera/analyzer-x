import { chromium } from 'playwright-core';
const b = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' });
const p = await (await b.newContext({ viewport: { width: 1500, height: 1200 } })).newPage();
p.on('pageerror', e => console.log('PAGEERROR', String(e).slice(0, 160)));
p.on('response', r => { if (r.url().includes('/api/strategies?')) console.log('NET', r.status(), decodeURIComponent(r.url()).replace(/^.*strategies\?/, '')); });
await p.goto('http://127.0.0.1:8503/backtest', { waitUntil: 'domcontentloaded', timeout: 90000 });
await p.waitForTimeout(9000);
const card = p.locator('h3:has-text("Stored strategies")').first()
  .locator('xpath=ancestor::div[contains(@class,"rounded")][1]');
const dlg = p.locator('[role="dialog"][aria-label="Filters"]');
const chips = () => card.locator('[aria-label^="remove filter"]').evaluateAll(
  x => x.map(e => (e.getAttribute('aria-label') || '').slice(14)));
await card.locator('button:has-text("Filters")').first().click();
await p.waitForTimeout(600);
// type a range FIRST, then tick the box: the range must grey out and stop counting
await dlg.locator('input[aria-label="Minimum take profit percent"]').fill('0.5');
await dlg.locator('input[aria-label="Maximum take profit percent"]').fill('2.5');
await dlg.locator('input[aria-label="Only rows whose take profit is wider than their stop loss"]').check();
await p.waitForTimeout(300);
const state = await dlg.evaluate((d) => {
  const g = (n) => d.querySelector(`input[aria-label="${n}"]`);
  return ["Minimum take profit percent", "Maximum take profit percent",
          "Minimum stop loss percent", "Maximum stop loss percent"]
    .map(n => ({ n, disabled: g(n).disabled, value: g(n).value }));
});
console.log('boxes:', JSON.stringify(state));
console.log('footer:', (await dlg.innerText()).split('\n').filter(l => l.startsWith('Apply will ask'))[0]);
await dlg.screenshot({ path: 'tpgtsl_modal.png' });
await dlg.locator('button:has-text("Apply")').click();
for (let i = 0; i < 60; i++) { await p.waitForTimeout(1000); if ((await chips()).length >= 1) break; }
await p.waitForTimeout(800);
console.log('chips:', JSON.stringify(await chips()));
const tbl = await card.evaluate((el) => {
  const t = el.querySelector('table');
  const head = [...t.querySelectorAll('thead th, thead td')].map(x => x.innerText.trim());
  const iTp = head.indexOf('TP%'), iSl = head.indexOf('SL%');
  let n = 0, bad = 0, minP = 99, maxP = 0;
  for (const tr of t.querySelectorAll('tbody tr')) {
    const c = [...tr.children].map(x => x.innerText.trim());
    const tp = parseFloat(c[iTp]), sl = parseFloat(c[iSl]);
    if (isNaN(tp) || isNaN(sl)) continue;
    n++; if (tp <= sl) bad++; const q = tp / sl; minP = Math.min(minP, q); maxP = Math.max(maxP, q);
  }
  return { n, bad, payoff: [minP.toFixed(2), maxP.toFixed(2)] };
});
console.log('table:', JSON.stringify(tbl));
console.log('caption:', (await card.locator('p').first().innerText()).split('·')[0].trim());
await p.locator('h3:has-text("Stored strategies")').first().scrollIntoViewIfNeeded();
await p.waitForTimeout(300);
const box = await card.boundingBox(), sy = await p.evaluate(() => window.scrollY);
await p.screenshot({ path: 'tpgtsl_bar.png', fullPage: true, clip: { x: box.x, y: box.y + sy, width: box.width, height: 175 } });
// untick: the typed range must come back
await card.locator('button:has-text("Filters")').first().click();
await p.waitForTimeout(500);
await dlg.locator('input[aria-label="Only rows whose take profit is wider than their stop loss"]').uncheck();
await p.waitForTimeout(300);
console.log('after untick:', (await dlg.innerText()).split('\n').filter(l => l.startsWith('Apply will ask'))[0]);
console.log('tp boxes:', await dlg.locator('input[aria-label="Minimum take profit percent"]').inputValue(),
  '/', await dlg.locator('input[aria-label="Maximum take profit percent"]').inputValue(),
  '| disabled now:', await dlg.locator('input[aria-label="Minimum take profit percent"]').isDisabled());
await b.close();
