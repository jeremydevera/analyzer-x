import { chromium } from 'playwright-core';
const b = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' });
const p = await (await b.newContext({ viewport: { width: 1500, height: 1100 } })).newPage();
p.on('pageerror', e => console.log('PAGEERROR', String(e).slice(0, 160)));
p.on('response', async r => { if (r.url().includes('/api/strategies?')) {
  let t = ''; if (r.status() >= 400) { try { t = (await r.text()).slice(0, 240); } catch {} }
  console.log('NET', r.status(), decodeURIComponent(r.url()).replace(/^.*strategies\?/, ''), t); } });
await p.goto('http://127.0.0.1:8503/backtest', { waitUntil: 'domcontentloaded', timeout: 90000 });
await p.waitForTimeout(9000);
const card = p.locator('h3:has-text("Stored strategies")').first()
  .locator('xpath=ancestor::div[contains(@class,"rounded")][1]');
const dlg = p.locator('[role="dialog"][aria-label="Filters"]');
const line = async () => (await card.locator('text=Filter:').first().locator('xpath=..').innerText()).replace(/\s+/g, ' ').trim();
console.log('legend gone:', !(await card.innerText()).includes('one row = one coin'));
console.log('empty line:', await line());
await card.locator('button:has-text("Filters")').first().click();
await p.waitForTimeout(600);
await dlg.locator('input[aria-label="Last N days"]').fill('30');
await dlg.locator('input[aria-label="Minimum win rate percent"]').fill('90');
await dlg.locator('input[aria-label="Maximum take profit percent"]').fill('5');
await p.waitForTimeout(300);
console.log('modal says:', (await dlg.innerText()).split('\n').filter(l => l.startsWith('Apply will ask'))[0]);
await dlg.locator('button:has-text("Apply")').click();
for (let i = 0; i < 90; i++) { await p.waitForTimeout(1000);
  if ((await card.locator('[aria-label^="remove filter"]').count()) === 3) break; }
await p.waitForTimeout(800);
console.log('applied line:', await line());
await p.locator('h3:has-text("Stored strategies")').first().scrollIntoViewIfNeeded();
await p.waitForTimeout(300);
const box = await card.boundingBox(), sy = await p.evaluate(() => window.scrollY);
await p.screenshot({ path: 'sentence.png', fullPage: true, clip: { x: box.x, y: box.y + sy, width: box.width, height: 210 } });
await b.close();
