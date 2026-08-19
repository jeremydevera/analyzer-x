import { chromium } from 'playwright';
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1920, height: 1050 } });
await page.goto('file://' + process.argv[2]);
await page.waitForTimeout(3000);
const heads = await page.locator('thead th').allInnerTexts();
console.log('HEADERS:', JSON.stringify(heads));
console.log('H1:', await page.locator('h1').innerText());
console.log('SUB:', await page.locator('.sub').innerText());
for (const id of ['KS25KC','DSQWE3','CHKCED','WLD3LY','X73RDX','KUEZKU','Y9QBCN']) {
  const find = page.locator('input#fid').first();
  await find.fill(id);
  await find.press('Enter');
  await page.waitForTimeout(1200);
  const row = page.locator('tbody tr').first();
  const cells = await row.locator('td').allInnerTexts();
  const o = {};
  heads.forEach((h, i) => { if (/ID|VERDICT|WIN %|PROFIT|WORST STREAK|STREAK LOSSES|THIS MONTH|TRADES$|WINS|LOSSES/.test(h)) o[h] = cells[i]; });
  console.log(id, JSON.stringify(o));
}
await page.screenshot({ path: '/tmp/pi_patched.png' });
await browser.close();
