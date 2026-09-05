import { chromium } from 'playwright-core';
const b = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' });
const p = await b.newPage({ viewport: { width: 1500, height: 1000 }, deviceScaleFactor: 2 });
await p.goto('http://127.0.0.1:8503/backtest', { waitUntil: 'domcontentloaded', timeout: 90000 });
await p.waitForTimeout(9000);
const h = p.locator('h3:has-text("Stored strategies")').first();
await h.scrollIntoViewIfNeeded();
const card = h.locator('xpath=ancestor::div[contains(@class,"rounded")][1]');
const box = await card.boundingBox();
await p.screenshot({ path: 'filters_after.png', clip: { x: box.x, y: box.y, width: box.width, height: 400 } });
// colours of the little labels, resolved by the browser
const probe = await p.evaluate(() => {
  const out = [];
  for (const l of document.querySelectorAll('label')) {
    const t = (l.innerText || '').trim().slice(0, 20);
    if (!t) continue;
    out.push({ t, color: getComputedStyle(l).color, cls: l.className.slice(0, 60) });
  }
  return out.slice(0, 12);
});
console.log(JSON.stringify(probe, null, 1));
await b.close();
