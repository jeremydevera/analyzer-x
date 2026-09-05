import { chromium } from 'playwright-core';
const b = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' });
const p = await b.newPage({ viewport: { width: 1500, height: 1200 } });
p.on('response', async r => {
  if (r.url().includes('/api/strategies')) {
    let body = '';
    if (r.status() >= 400) { try { body = (await r.text()).slice(0, 200); } catch {} }
    console.log(r.status(), decodeURIComponent(r.url()).slice(0, 200), body);
  }
});
await p.goto('http://localhost:8503/backtest', { waitUntil: 'domcontentloaded', timeout: 90000 });
await p.waitForTimeout(9000);
const card = p.locator('h3:has-text("Stored strategies")').first()
  .locator('xpath=ancestor::div[contains(@class,"rounded")][1]');
await card.locator('select[aria-label="Timeframe"]').selectOption('1h');
await card.locator('input[aria-label="Minimum win rate percent"]').fill('55');
const t0 = Date.now();
await card.locator('button:has-text("Apply")').first().click();
for (let i = 0; i < 60; i++) {
  await p.waitForTimeout(1000);
  const t = await card.locator('button:has-text("Apply")').first().innerText();
  if (!/searching/i.test(t)) break;
}
console.log('settled after', ((Date.now() - t0) / 1000).toFixed(1), 's');
await b.close();
