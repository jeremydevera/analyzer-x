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
await dlg.locator('input[aria-label="Minimum take profit percent"]').fill('0.5');
await dlg.locator('input[aria-label="Maximum take profit percent"]').fill('2.5');
await dlg.locator('input[aria-label="Minimum stop loss percent"]').fill('0.5');
await dlg.locator('input[aria-label="Maximum stop loss percent"]').fill('1.5');
await p.waitForTimeout(300);
await dlg.screenshot({ path: 'between_modal.png' });
console.log('footer:', (await dlg.innerText()).split('\n').filter(l => l.startsWith('Apply will ask'))[0]);
await dlg.locator('button:has-text("Apply")').click();
for (let i = 0; i < 60; i++) { await p.waitForTimeout(1000); if ((await chips()).length === 2) break; }
await p.waitForTimeout(800);
console.log('chips:', JSON.stringify(await chips()));
// the TABLE must obey: read the tp/sl columns
const cols = await p.evaluate(() => {
  const t = [...document.querySelectorAll('table')].pop();
  const head = [...t.querySelectorAll('thead th, thead td')].map(x => x.innerText.trim());
  const iTp = head.findIndex(h => /^TP%/i.test(h)), iSl = head.findIndex(h => /^SL%/i.test(h));
  const tps = [], sls = [];
  for (const tr of t.querySelectorAll('tbody tr')) {
    const c = [...tr.children].map(x => x.innerText.trim());
    if (c.length > Math.max(iTp, iSl)) { tps.push(parseFloat(c[iTp])); sls.push(parseFloat(c[iSl])); }
  }
  return { head: head.slice(0, 12), n: tps.length, tp: [Math.min(...tps), Math.max(...tps)], sl: [Math.min(...sls), Math.max(...sls)] };
});
console.log('table:', JSON.stringify(cols));
await p.locator('h3:has-text("Stored strategies")').first().scrollIntoViewIfNeeded();
await p.waitForTimeout(300);
const box = await card.boundingBox(), sy = await p.evaluate(() => window.scrollY);
await p.screenshot({ path: 'between_bar.png', fullPage: true, clip: { x: box.x, y: box.y + sy, width: box.width, height: 175 } });
// removing the TP chip must clear BOTH ends
await card.locator('[aria-label^="remove filter TP"]').click();
for (let i = 0; i < 60; i++) { await p.waitForTimeout(1000); if ((await chips()).length === 1) break; }
console.log('after x:', JSON.stringify(await chips()));
await card.locator('button:has-text("Filters")').first().click();
await p.waitForTimeout(500);
console.log('tp boxes now: "' + await dlg.locator('input[aria-label="Minimum take profit percent"]').inputValue()
  + '" / "' + await dlg.locator('input[aria-label="Maximum take profit percent"]').inputValue() + '"');
await b.close();
