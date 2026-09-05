import { chromium } from 'playwright-core';
const b = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' });
const p = await b.newPage({ viewport: { width: 1500, height: 1400 }, deviceScaleFactor: 1 });
p.on('pageerror', e => console.log('PAGEERROR', String(e).slice(0, 200)));
await p.goto('http://localhost:8503/backtest', { waitUntil: 'domcontentloaded', timeout: 90000 });
await p.waitForTimeout(9000);
const card = p.locator('h3:has-text("Stored strategies")').first()
  .locator('xpath=ancestor::div[contains(@class,"rounded")][1]');
const shot = async (name, off = 200, h = 300) => {
  await p.locator('h3:has-text("Stored strategies")').first().scrollIntoViewIfNeeded();
  await p.waitForTimeout(400);
  const box = await card.boundingBox();
  const sy = await p.evaluate(() => window.scrollY);
  await p.screenshot({ path: name, fullPage: true,
    clip: { x: box.x, y: box.y + off + sy, width: box.width, height: h } });
};

// 1. two filters typed -> the button must say what will be sent
await card.locator('select[aria-label="Timeframe"]').selectOption('1h');
await card.locator('input[aria-label="Minimum win rate percent"]').fill('55');
await p.waitForTimeout(300);
console.log('button:', (await card.locator('button:has-text("Apply")').first().innerText()).replace(/\n/g, ' '));
console.log('pending note:', await card.locator('text=not applied yet').count());
await shot('drive_1_pending.png', 190, 320);

// 2. apply, wait for the rows
await card.locator('button:has-text("Apply")').first().click();
for (let i = 0; i < 40; i++) {
  await p.waitForTimeout(1000);
  const t = await card.locator('button:has-text("Apply")').first().innerText();
  if (!/searching/i.test(t)) break;
}
await p.waitForTimeout(1500);
const chips = await card.locator('[aria-label^="remove filter"]').evaluateAll(
  bs => bs.map(x => x.closest('span')?.innerText.trim()));
console.log('chips:', JSON.stringify(chips));
console.log('caption:', (await card.locator('p').first().innerText()).slice(0, 220).replace(/\n/g, ' '));
console.log('clear all:', await card.locator('button:has-text("clear all")').count());
await shot('drive_2_applied.png', 190, 340);

// 3. remove ONE chip with its x
if (chips.length) {
  await card.locator('[aria-label^="remove filter"]').first().click();
  for (let i = 0; i < 40; i++) {
    await p.waitForTimeout(1000);
    const t = await card.locator('button:has-text("Apply")').first().innerText();
    if (!/searching/i.test(t)) break;
  }
  await p.waitForTimeout(1200);
  const left = await card.locator('[aria-label^="remove filter"]').evaluateAll(
    bs => bs.map(x => x.closest('span')?.innerText.trim()));
  console.log('after one x:', JSON.stringify(left));
  console.log('tf select now:', await card.locator('select[aria-label="Timeframe"]').inputValue());
  console.log('win box now:', await card.locator('input[aria-label="Minimum win rate percent"]').inputValue());
  await shot('drive_3_one_removed.png', 190, 340);
}
// 4. clear all
if (await card.locator('button:has-text("clear all")').count()) {
  await card.locator('button:has-text("clear all")').click();
  await p.waitForTimeout(2500);
  console.log('after clear all:', (await card.locator('text=showing rows where').first()
    .locator('xpath=..').innerText()).replace(/\n/g, ' ').slice(0, 160));
}
await b.close();
