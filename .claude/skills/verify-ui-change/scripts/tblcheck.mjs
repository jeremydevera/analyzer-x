import { chromium } from 'playwright-core';
const b = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' });
const p = await (await b.newContext({ viewport: { width: 1500, height: 1200 } })).newPage();
await p.goto('http://127.0.0.1:8503/backtest', { waitUntil: 'domcontentloaded', timeout: 90000 });
await p.waitForTimeout(9000);
const card = p.locator('h3:has-text("Stored strategies")').first()
  .locator('xpath=ancestor::div[contains(@class,"rounded")][1]');
const dlg = p.locator('[role="dialog"][aria-label="Filters"]');
await card.locator('button:has-text("Filters")').first().click();
await p.waitForTimeout(500);
await dlg.locator('input[aria-label="Minimum take profit percent"]').fill('0.5');
await dlg.locator('input[aria-label="Maximum take profit percent"]').fill('2.5');
await dlg.locator('input[aria-label="Minimum stop loss percent"]').fill('0.5');
await dlg.locator('input[aria-label="Maximum stop loss percent"]').fill('1.5');
await dlg.locator('button:has-text("Apply")').click();
for (let i = 0; i < 60; i++) { await p.waitForTimeout(1000);
  if ((await card.locator('[aria-label^="remove filter"]').count()) === 2) break; }
await p.waitForTimeout(1500);
const got = await card.evaluate((el) => {
  const t = el.querySelector('table');
  const head = [...t.querySelectorAll('thead th, thead td')].map(x => x.innerText.trim());
  const iTp = head.indexOf('TP%'), iSl = head.indexOf('SL%');
  const tp = [], sl = [];
  for (const tr of t.querySelectorAll('tbody tr')) {
    const c = [...tr.children].map(x => x.innerText.trim());
    const a = parseFloat(c[iTp]), s = parseFloat(c[iSl]);
    if (!isNaN(a)) tp.push(a); if (!isNaN(s)) sl.push(s);
  }
  return { head: head.slice(0, 10), iTp, iSl, n: tp.length,
           tp: [Math.min(...tp), Math.max(...tp)], sl: [Math.min(...sl), Math.max(...sl)] };
});
console.log(JSON.stringify(got));
console.log('outside the range:', got.tp[0] < 0.5 || got.tp[1] > 2.5 || got.sl[0] < 0.5 || got.sl[1] > 1.5);
await b.close();
