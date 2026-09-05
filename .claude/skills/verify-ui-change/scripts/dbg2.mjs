import { chromium } from 'playwright-core';
const b = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' });
const p = await b.newPage({ viewport: { width: 1500, height: 1400 } });
p.on('pageerror', e => console.log('PAGEERROR', String(e).slice(0, 160)));
await p.goto('http://127.0.0.1:8503/backtest', { waitUntil: 'domcontentloaded', timeout: 90000 });
await p.waitForTimeout(9000);
const card = p.locator('h3:has-text("Stored strategies")').first()
  .locator('xpath=ancestor::div[contains(@class,"rounded")][1]');
const chips = () => card.locator('[aria-label^="remove filter"]').evaluateAll(
  x => x.map(e => (e.getAttribute('aria-label') || '').slice(14)));
const total = async () => (await card.locator('p').first().innerText()).split('·')[0].trim();
const waitChips = async (want) => {
  for (let i = 0; i < 60; i++) {
    await p.waitForTimeout(1000);
    const c = await chips();
    if (c.length === want) return c;
  }
  return await chips();
};
const shot = async (n, off, h) => {
  await p.locator('h3:has-text("Stored strategies")').first().scrollIntoViewIfNeeded();
  await p.waitForTimeout(300);
  const box = await card.boundingBox();
  const sy = await p.evaluate(() => window.scrollY);
  await p.screenshot({ path: n, fullPage: true, clip: { x: box.x, y: box.y + off + sy, width: box.width, height: h } });
};
await card.locator('select[aria-label="Timeframe"]').selectOption('1h');
await card.locator('input[aria-label="Minimum trades"]').fill('100');
await card.locator('input[aria-label="Minimum win rate percent"]').fill('55');
await card.locator('select[aria-label="Sizing"]').selectOption({ index: 1 });
await shot('ok1_pending.png', 80, 360);
await card.locator('button:has-text("Apply")').first().click();
console.log('applied ->', JSON.stringify(await waitChips(4)), '| total', await total());
await shot('ok2_chips.png', 80, 400);
// one x
await card.locator('[aria-label="remove filter win % ≥ 55"]').click();
console.log('after one x ->', JSON.stringify(await waitChips(3)), '| total', await total(),
  '| win box "' + await card.locator('input[aria-label="Minimum win rate percent"]').inputValue() + '"');
await shot('ok3_after_x.png', 80, 400);
// clear all
await card.locator('button:has-text("clear all")').click();
console.log('after clear all ->', JSON.stringify(await waitChips(0)), '| total', await total(),
  '| tf "' + await card.locator('select[aria-label="Timeframe"]').inputValue() + '"',
  '| trades "' + await card.locator('input[aria-label="Minimum trades"]').inputValue() + '"',
  '| sizing "' + await card.locator('select[aria-label="Sizing"]').inputValue() + '"');
console.log('line:', (await card.locator('text=showing rows where').first().locator('xpath=..').innerText()).replace(/\n/g, ' ').slice(0, 90));
await shot('ok4_cleared.png', 80, 400);
await b.close();
