import { chromium } from 'playwright-core';
const b = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' });
const p = await b.newPage({ viewport: { width: 1500, height: 1400 } });
await p.addInitScript(() => {
  const f = window.fetch; let n = 0;
  window.fetch = (...a) => { const u = String(a[0]); if (u.includes('/api/strategies?')) {
    const id = ++n, t = Date.now();
    console.log('S', id, decodeURIComponent(u).replace(/^.*strategies\?/, ''));
    return f(...a).then(r => { console.log('E', id, r.status, Date.now() - t); return r; });
  } return f(...a); };
});
p.on('console', m => { const t = m.text(); if (/^[SE] \d/.test(t)) console.log(t); });
await p.goto('http://127.0.0.1:8503/backtest', { waitUntil: 'domcontentloaded', timeout: 90000 });
await p.waitForTimeout(9000);
const card = p.locator('h3:has-text("Stored strategies")').first()
  .locator('xpath=ancestor::div[contains(@class,"rounded")][1]');
await card.locator('select[aria-label="Timeframe"]').selectOption('1h');
await card.locator('input[aria-label="Minimum trades"]').fill('100');
await card.locator('input[aria-label="Minimum win rate percent"]').fill('55');
console.log('APPLY');
await card.locator('button:has-text("Apply")').first().click();
for (const w of [3000, 3000, 6000, 10000]) {
  await p.waitForTimeout(w);
  const chips = await card.locator('[aria-label^="remove filter"]').evaluateAll(
    x => x.map(e => (e.getAttribute('aria-label') || '').slice(14)));
  const line = (await card.locator('text=showing rows where').first().locator('xpath=..').innerText()).replace(/\n/g, ' ').slice(0, 110);
  console.log('  chips', JSON.stringify(chips), '|', line);
}
await b.close();
