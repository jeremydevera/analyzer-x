import { chromium } from 'playwright';
const [,, path, depId] = process.argv;
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1920, height: 1050 } });
await page.goto('file://' + path);
await page.waitForTimeout(4000);
const money = s => parseFloat(String(s).replace(/[$,+]/g,'').replace(/−/g,'-'));
console.log('H1:', await page.locator('h1').innerText());
console.log('SUB:', await page.locator('.sub').innerText());
const body = await page.locator('body').innerText();
console.log('trapline:', (body.match(/The highest win rate in this grid[^.]*\./)||['MISSING'])[0].slice(0,160));
console.log('live panel:', (body.match(/Live right now[^\n]*/i)||['none'])[0]);
const heads = await page.locator('thead th').allInnerTexts();
const pIdx = heads.findIndex(h => /PROFIT TOTAL/i.test(h));
if (depId) {
  await page.locator('input#fid').fill(depId);
  await page.waitForTimeout(1500);
  const cells = await page.locator('tbody tr').first().locator('td').allInnerTexts();
  await page.locator('tbody tr').first().click();
  await page.waitForTimeout(1500);
  const b2 = await page.locator('body').innerText();
  const tot = money(((b2.match(/TOTAL PROFIT[^\n]*/i)||[''])[0].match(/[−+-]?[\d,]+\.?\d*/g)||[]).pop());
  console.log(depId, 'verdict:', cells[2], '| row profit', money(cells[pIdx]), 'vs log', tot,
              '| match:', Math.abs(money(cells[pIdx])-tot)<0.06);
}
await page.screenshot({ path: '/tmp/coin_check.png' });
await browser.close();
