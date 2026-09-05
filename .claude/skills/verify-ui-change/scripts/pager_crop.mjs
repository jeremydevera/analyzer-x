import { chromium } from 'playwright-core';
const b = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' });
const p = await b.newPage({ viewport: { width: 1500, height: 1000 }, deviceScaleFactor: 1 });
await p.goto('http://127.0.0.1:8503/backtest', { waitUntil: 'domcontentloaded', timeout: 90000 });
await p.waitForTimeout(12000);
for (const [name, title] of [['strat', 'Stored strategies'], ['store', 'Backtest store']]) {
  const pager = p.locator(`h3:has-text("${title}")`).first()
    .locator('xpath=ancestor::div[contains(@class,"rounded-2xl")][1]')
    .locator('xpath=.//button[normalize-space(text())="prev"]/ancestor::div[2]');
  await pager.first().scrollIntoViewIfNeeded();
  await p.waitForTimeout(400);
  const bx = await pager.first().boundingBox();
  await p.screenshot({ path: `pagerc_${name}.png`,
    clip: { x: bx.x - 8, y: bx.y - 130, width: Math.min(bx.width + 16, 1490), height: bx.height + 150 } });
}
await b.close();
