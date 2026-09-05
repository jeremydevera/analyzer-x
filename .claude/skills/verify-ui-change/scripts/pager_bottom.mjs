import { chromium } from 'playwright-core';
const b = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' });
const p = await b.newPage({ viewport: { width: 1500, height: 1000 }, deviceScaleFactor: 1 });
await p.goto('http://127.0.0.1:8503/backtest', { waitUntil: 'domcontentloaded', timeout: 90000 });
await p.waitForTimeout(12000);

for (const [name, title] of [['strat', 'Stored strategies'], ['store', 'Backtest store']]) {
  const h = p.locator(`h3:has-text("${title}")`).first();
  if (!await h.count()) { console.log(name, 'MISSING PANEL'); continue; }
  const card = h.locator('xpath=ancestor::div[contains(@class,"rounded-2xl")][1]');
  // where is the pager relative to the table inside this card?
  const geo = await card.evaluate((el) => {
    const prev = el.querySelector('button');
    const pager = [...el.querySelectorAll('button')].find(x => x.textContent.trim() === 'prev');
    const table = el.querySelector('table');
    if (!pager || !table) return { pager: !!pager, table: !!table };
    const pr = pager.getBoundingClientRect(), tr = table.getBoundingClientRect();
    return { pagerTop: Math.round(pr.top), tableTop: Math.round(tr.top),
             tableBottom: Math.round(tr.bottom), below: pr.top > tr.top };
  });
  console.log(name, JSON.stringify(geo));
  await card.scrollIntoViewIfNeeded();
  await p.waitForTimeout(400);
  await card.screenshot({ path: `pager_${name}.png` });
}
await b.close();
