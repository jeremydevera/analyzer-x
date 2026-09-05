import { chromium } from 'playwright-core';
const b = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' });
const p = await b.newPage({ viewport: { width: 1500, height: 1000 }, deviceScaleFactor: 1 });
await p.goto('http://127.0.0.1:8503/backtest', { waitUntil: 'domcontentloaded', timeout: 90000 });
await p.waitForTimeout(12000);
for (const [name, title] of [['strat', 'Stored strategies'], ['store', 'Backtest store']]) {
  const card = p.locator(`h3:has-text("${title}")`).first()
    .locator('xpath=ancestor::div[contains(@class,"rounded-2xl")][1]');
  await card.scrollIntoViewIfNeeded();
  await p.waitForTimeout(400);
  const bx = await card.boundingBox();
  await p.screenshot({ path: `pagert_${name}.png`,
    clip: { x: bx.x, y: bx.y, width: bx.width, height: 340 } });
}
await b.close();
