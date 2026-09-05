import { chromium } from 'playwright-core';
const b = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' });
const p = await b.newPage({ viewport: { width: 1500, height: 1200 } });
await p.addInitScript(() => {
  const f = window.fetch;
  let n = 0;
  window.fetch = (...a) => {
    const id = ++n, u = String(a[0]);
    if (u.includes('/api/strategies')) {
      const t = Date.now();
      console.log('FETCH-START', id, decodeURIComponent(u).slice(0, 150));
      return f(...a).then(r => { console.log('FETCH-END', id, r.status, Date.now() - t, 'ms'); return r; },
                          e => { console.log('FETCH-ERR', id, String(e)); throw e; });
    }
    return f(...a);
  };
});
p.on('console', m => { const t = m.text(); if (t.startsWith('FETCH')) console.log(t); });
await p.goto('http://127.0.0.1:8503/backtest', { waitUntil: 'domcontentloaded', timeout: 90000 });
await p.waitForTimeout(9000);
const card = p.locator('h3:has-text("Stored strategies")').first()
  .locator('xpath=ancestor::div[contains(@class,"rounded")][1]');
await card.locator('select[aria-label="Timeframe"]').selectOption('1h');
await card.locator('input[aria-label="Minimum win rate percent"]').fill('55');
await card.locator('input[aria-label="Maximum stop loss percent"]').fill('2');
await card.locator('select[aria-label="Sizing"]').selectOption({ index: 1 });
console.log('--- apply');
await card.locator('button:has-text("Apply")').first().click();
await p.waitForTimeout(75000);
console.log('chips:', JSON.stringify(await card.locator('[aria-label^="remove filter"]').evaluateAll(
  bs => bs.map(x => x.closest('span')?.innerText.trim()))));
console.log('caption:', (await card.locator('p').first().innerText()).slice(0, 90).replace(/\n/g, ' '));
await b.close();
