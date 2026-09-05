import { chromium } from 'playwright-core';
const b = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' });
const p = await b.newPage({ viewport: { width: 1500, height: 1400 } });
p.on('pageerror', e => console.log('PAGEERROR', String(e).slice(0, 160)));
await p.goto('http://127.0.0.1:8503/backtest', { waitUntil: 'domcontentloaded', timeout: 90000 });
await p.waitForTimeout(9000);
const card = p.locator('h3:has-text("Stored strategies")').first()
  .locator('xpath=ancestor::div[contains(@class,"rounded")][1]');
const chips = () => card.locator('[aria-label^="remove filter"]').evaluateAll(
  bs => bs.map(x => (x.getAttribute('aria-label') || '').replace('remove filter ', '')));
const cap = async () => (await card.locator('p').first().innerText()).split('·')[0].trim();
const settle = async () => {
  for (let i = 0; i < 90; i++) {
    await p.waitForTimeout(1000);
    const t = await card.locator('button:has-text("Apply")').first().innerText();
    if (!/searching/i.test(t)) { await p.waitForTimeout(1200); return i + 1; }
  }
  return -1;
};
const shot = async (n, off, h) => {
  await p.locator('h3:has-text("Stored strategies")').first().scrollIntoViewIfNeeded();
  await p.waitForTimeout(300);
  const box = await card.boundingBox();
  const sy = await p.evaluate(() => window.scrollY);
  await p.screenshot({ path: n, fullPage: true, clip: { x: box.x, y: box.y + off + sy, width: box.width, height: h } });
};

await card.locator('select[aria-label="Timeframe"]').selectOption('1h');
await card.locator('input[aria-label="Minimum win rate percent"]').fill('55');
await card.locator('input[aria-label="Minimum trades"]').fill('100');
await p.waitForTimeout(300);
console.log('button:', (await card.locator('button:has-text("Apply")').first().innerText()).replace(/\n/g, ' '));
await shot('v1_pending.png', 150, 340);
await card.locator('button:has-text("Apply")').first().click();
await settle();
console.log('chips:', JSON.stringify(await chips()), '| total:', await cap());
await shot('v2_chips.png', 150, 340);

// remove the win% chip by its own x
const one = card.locator('[aria-label="remove filter win % ≥ 55"]');
console.log('win chip found:', await one.count());
await one.click();
await settle();
console.log('after x:', JSON.stringify(await chips()), '| total:', await cap(),
  '| win box:', await card.locator('input[aria-label="Minimum win rate percent"]').inputValue());
await shot('v3_after_x.png', 150, 340);

await card.locator('button:has-text("clear all")').click();
await settle();
console.log('after clear all:', JSON.stringify(await chips()), '| total:', await cap(),
  '| tf:', await card.locator('select[aria-label="Timeframe"]').inputValue(),
  '| trades:', await card.locator('input[aria-label="Minimum trades"]').inputValue());
console.log('summary line:', (await card.locator('text=showing rows where').first().locator('xpath=..').innerText()).replace(/\n/g, ' ').slice(0, 120));
await shot('v4_cleared.png', 150, 340);
await b.close();
