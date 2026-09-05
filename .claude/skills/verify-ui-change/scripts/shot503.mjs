import { chromium } from 'playwright-core';
const b = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' });
const p = await b.newPage({ viewport: { width: 1500, height: 1400 } });
await p.goto('http://127.0.0.1:8503/backtest', { waitUntil: 'domcontentloaded', timeout: 90000 });
await p.waitForTimeout(9000);
const card = p.locator('h3:has-text("Stored strategies")').first()
  .locator('xpath=ancestor::div[contains(@class,"rounded")][1]');
await card.locator('select[aria-label="Timeframe"]').selectOption('1h');
await card.locator('input[aria-label="Minimum win rate percent"]').fill('55');
await card.locator('input[aria-label="Maximum stop loss percent"]').fill('2');
await card.locator('button:has-text("Apply")').first().click();
for (let i = 0; i < 60; i++) {
  await p.waitForTimeout(1000);
  const t = await card.locator('button:has-text("Apply")').first().innerText();
  if (!/searching/i.test(t)) break;
}
await p.waitForTimeout(1500);
console.log('---- panel text ----');
console.log((await card.innerText()).split('\n').slice(0, 26).join('\n'));
await p.locator('h3:has-text("Stored strategies")').first().scrollIntoViewIfNeeded();
await p.waitForTimeout(300);
const box = await card.boundingBox();
const sy = await p.evaluate(() => window.scrollY);
await p.screenshot({ path: 'state_503.png', fullPage: true,
  clip: { x: box.x, y: box.y + sy, width: box.width, height: 520 } });
await b.close();
