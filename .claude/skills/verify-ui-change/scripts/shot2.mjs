import { chromium } from 'playwright-core';
const b = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' });
const p = await b.newPage({ viewport: { width: 1500, height: 1400 }, deviceScaleFactor: 1 });
await p.goto('http://127.0.0.1:8503/backtest', { waitUntil: 'domcontentloaded', timeout: 90000 });
await p.waitForTimeout(9000);
const h = p.locator('h3:has-text("Stored strategies")').first();
await h.scrollIntoViewIfNeeded();
await p.waitForTimeout(500);
const box = await h.locator('xpath=ancestor::div[contains(@class,"rounded")][1]').boundingBox();
await p.screenshot({ path: 'filters_rest.png', fullPage: true,
  clip: { x: box.x, y: box.y + 200 + (await p.evaluate(() => window.scrollY)), width: box.width, height: 260 } });
await b.close();
