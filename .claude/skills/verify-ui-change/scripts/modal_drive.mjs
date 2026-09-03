import { chromium } from 'playwright-core';
const b = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' });
const p = await (await b.newContext({ viewport: { width: 1500, height: 1100 } })).newPage();
p.on('pageerror', e => console.log('PAGEERROR', String(e).slice(0, 160)));
await p.goto('http://127.0.0.1:8503/backtest', { waitUntil: 'domcontentloaded', timeout: 90000 });
await p.waitForTimeout(9000);
const card = p.locator('h3:has-text("Stored strategies")').first()
  .locator('xpath=ancestor::div[contains(@class,"rounded")][1]');
const dlg = p.locator('[role="dialog"][aria-label="Filters"]');
const chips = () => card.locator('[aria-label^="remove filter"]').evaluateAll(
  x => x.map(e => (e.getAttribute('aria-label') || '').slice(14)));
const total = async () => (await card.locator('p').first().innerText()).split('·')[0].trim();
const waitChips = async (want) => { for (let i = 0; i < 90; i++) { await p.waitForTimeout(1000);
  if ((await chips()).length === want) return await chips(); } return await chips(); };
const badge = async () => (await card.locator('button:has-text("Filters")').first().innerText()).replace(/\s+/g, ' ').trim();

await card.locator('button:has-text("Filters")').first().click();
await p.waitForTimeout(600);
console.log('open:', await dlg.isVisible());
await dlg.locator('select[aria-label="Timeframe"]').selectOption('1h');
await dlg.locator('input[aria-label="Minimum trades"]').fill('100');
await dlg.locator('input[aria-label="Minimum win rate percent"]').fill('55');
await p.waitForTimeout(300);
console.log('footer:', (await dlg.innerText()).split('\n').slice(-6).join(' | '));
await dlg.screenshot({ path: 'md_filled.png' });
await dlg.locator('button:has-text("Apply")').click();
await p.waitForTimeout(600);
console.log('closed on apply:', !(await dlg.isVisible()));
console.log('chips:', JSON.stringify(await waitChips(3)), '| total', await total(), '| button:', await badge());
await p.locator('h3:has-text("Stored strategies")').first().scrollIntoViewIfNeeded();
await p.waitForTimeout(300);
let box = await card.boundingBox(), sy = await p.evaluate(() => window.scrollY);
await p.screenshot({ path: 'md_bar_applied.png', fullPage: true, clip: { x: box.x, y: box.y + sy, width: box.width, height: 180 } });
// one x
await card.locator('[aria-label="remove filter win % ≥ 55"]').click();
console.log('after x:', JSON.stringify(await waitChips(2)), '| button:', await badge());
// reopen: the box must be empty
await card.locator('button:has-text("Filters")').first().click();
await p.waitForTimeout(500);
console.log('win box after x: "' + await dlg.locator('input[aria-label="Minimum win rate percent"]').inputValue() + '"');
await dlg.locator('button:has-text("clear all")').click();
await p.waitForTimeout(600);
console.log('after clear all:', JSON.stringify(await waitChips(0)), '| total', await total(), '| button:', await badge());
console.log('tf now: "' + await dlg.locator('select[aria-label="Timeframe"]').inputValue() + '" trades "' + await dlg.locator('input[aria-label="Minimum trades"]').inputValue() + '"');
// escape closes
await p.keyboard.press('Escape');
await p.waitForTimeout(400);
console.log('escape closed:', !(await dlg.isVisible()));
await b.close();
