import { chromium } from 'playwright';
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1920, height: 1050 } });
await page.goto('file://' + process.argv[2]);
await page.waitForTimeout(4000);
const money = s => parseFloat(String(s).replace(/[$,+]/g,'').replace(/−/g,'-'));
console.log('H1:', await page.locator('h1').innerText());
console.log('SUB:', await page.locator('.sub').innerText());
const body = await page.locator('body').innerText();
console.log('prov 75 signals:', /75 signals/.test(body));
console.log('live panel:', (body.match(/Live right now[^\n]*/i)||['MISSING'])[0]);
console.log('count line:', (body.match(/[\d,]+ OF [\d,]+ SHOWN[^\n]*/i)||['MISSING'])[0]);
const heads = await page.locator('thead th').allInnerTexts();
const pIdx = heads.findIndex(h => /PROFIT TOTAL/i.test(h));
for (const id of ['4SNUHQ','2U78FY','ZYEBCG']) {
  await page.locator('input#fid').fill(id);
  await page.waitForTimeout(1500);
  const cells = await page.locator('tbody tr').first().locator('td').allInnerTexts();
  await page.locator('tbody tr').first().click();
  await page.waitForTimeout(1200);
  const b2 = await page.locator('body').innerText();
  const tot = money(((b2.match(/TOTAL PROFIT[^\n]*/i)||[''])[0].match(/[−+-]?[\d,]+\.?\d*/g)||[]).pop());
  const rowP = money(cells[pIdx]);
  console.log(id, 'verdict:', cells[2], '| row profit', rowP, 'vs log total', tot, '| match:', Math.abs(rowP-tot)<0.06);
}
await page.locator('input#fid').fill('');
await page.screenshot({ path: '/tmp/apex_check.png', fullPage: false });
await browser.close();
