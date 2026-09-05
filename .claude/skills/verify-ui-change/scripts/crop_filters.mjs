import { chromium } from 'playwright-core';
const b = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' });
const p = await b.newPage({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 1 });
await p.goto('http://127.0.0.1:8503/backtest', { waitUntil: 'domcontentloaded', timeout: 90000 });
await p.waitForTimeout(9000);
const h = p.locator('h3:has-text("Stored strategies"), h2:has-text("Stored strategies")').first();
await h.scrollIntoViewIfNeeded();
// the card that contains the heading
const card = h.locator('xpath=ancestor::div[contains(@class,"rounded")][1]');
const box = await card.boundingBox();
console.log('card box', JSON.stringify(box));
if (box) {
  await p.screenshot({ path: 'crop_strategies.png',
    clip: { x: box.x, y: box.y, width: box.width, height: Math.min(box.height, 620) } });
}
await b.close();
