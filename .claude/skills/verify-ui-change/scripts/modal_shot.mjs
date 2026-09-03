import { chromium } from 'playwright-core';
const dark = process.env.DARK === '1';
const b = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' });
const ctx = await b.newContext({ viewport: { width: 1500, height: 1100 } });
if (dark) await ctx.addInitScript(() => { try { localStorage.setItem('theme', 'dark'); } catch {} });
const p = await ctx.newPage();
p.on('pageerror', e => console.log('PAGEERROR', String(e).slice(0, 160)));
await p.goto('http://127.0.0.1:8503/backtest', { waitUntil: 'domcontentloaded', timeout: 90000 });
await p.waitForTimeout(9000);
const card = p.locator('h3:has-text("Stored strategies")').first()
  .locator('xpath=ancestor::div[contains(@class,"rounded")][1]');
await p.locator('h3:has-text("Stored strategies")').first().scrollIntoViewIfNeeded();
await p.waitForTimeout(400);
let box = await card.boundingBox(); let sy = await p.evaluate(() => window.scrollY);
await p.screenshot({ path: dark ? 'm_bar_dark.png' : 'm_bar.png', fullPage: true,
  clip: { x: box.x, y: box.y + sy, width: box.width, height: 170 } });
// open it
await card.locator('button:has-text("Filters")').first().click();
await p.waitForTimeout(700);
const dlg = p.locator('[role="dialog"][aria-label="Filters"]');
console.log('dialog visible:', await dlg.isVisible());
await dlg.screenshot({ path: dark ? 'm_modal_dark.png' : 'm_modal.png' });
// the fields must all be the same width
const w = await p.evaluate(() => {
  const d = document.querySelector('[role="dialog"][aria-label="Filters"]');
  const out = [];
  for (const el of d.querySelectorAll('select,input')) {
    if (el.type === 'checkbox') continue;
    const r = el.getBoundingClientRect();
    out.push({ n: el.getAttribute('aria-label') || el.type, w: Math.round(r.width), x: Math.round(r.x) });
  }
  return out;
});
console.log(JSON.stringify(w));
await b.close();
