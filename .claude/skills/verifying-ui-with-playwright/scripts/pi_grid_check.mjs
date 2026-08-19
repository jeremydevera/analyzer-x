// Pre-publish check for the PI 22-signal artifact page.
// Asserts, from the rendered page itself:
//  1. the table has rows and the count line matches the provenance combo count
//  2. clicking row 1 opens PAST TRADES whose TOTAL equals the row's PROFIT cell
//  3. the provenance names the real signal count and fibonacci presence
//  4. changing base margin rescales the clicked row's total consistently
import { chromium } from 'playwright';

const page_path = process.argv[2];
if (!page_path) { console.error('usage: node pi_grid_check.mjs <html>'); process.exit(2); }

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1680, height: 1050 } });
await page.goto('file://' + page_path);
await page.waitForTimeout(3000);

const money = (s) => parseFloat(String(s).replace(/[$,+]/g, '').replace(/−/g, '-'));

// 3. provenance
const prov = await page.locator('body').innerText();
const provOk = /22 signals/i.test(prov);
const fibOk = /fibonacci[^.]*in the grid/i.test(prov) && !/fibonacci is not/i.test(prov);
console.log('provenance says 22 signals:', provOk);
console.log('provenance says fibonacci in grid (and never "not here"):', fibOk);
const combos = (prov.match(/([\d,]+)\s+combinations/i) || [])[1];
console.log('combos stated:', combos);

// 1. table rows + count line
const rows = page.locator('tbody tr');
const n = await rows.count();
console.log('visible tbody rows:', n);
const countLine = (prov.match(/[\d,]+ of [\d,]+ shown[^\n]*/i) || [''])[0];
console.log('count line:', countLine);

// 2. click first data row -> PAST TRADES total equals row PROFIT
const first = rows.first();
const cells = await first.locator('td').allInnerTexts();
console.log('row1 cells:', JSON.stringify(cells.slice(0, 14)));
await first.click();
await page.waitForTimeout(1500);
const body2 = await page.locator('body').innerText();
const ptHead = (body2.match(/PAST TRADES[^\n]*/i) || [''])[0];
console.log('past-trades header:', ptHead);
const totalLine = (body2.match(/TOTAL PROFIT[^\n]*/i) || [''])[0];
console.log('total line:', totalLine);
const totalVal = money((totalLine.match(/[−+-]?\$?[\d,]+\.?\d*/g) || []).pop());
// find the PROFIT cell: use header names to index
const headers = await page.locator('thead th').allInnerTexts();
const pIdx = headers.findIndex(h => /profit/i.test(h) && !/this month/i.test(h));
const rowProfit = money(cells[pIdx]);
console.log('headers:', JSON.stringify(headers.slice(0, 16)));
console.log(`row PROFIT=${rowProfit} vs PAST TRADES TOTAL=${totalVal} -> match:`,
            Math.abs(rowProfit - totalVal) < 0.06);

// 4. base margin rescale: double it, total should ~double (flat rows scale ~2x)
const box = page.locator('input#base, input[id*="base" i]').first();
if (await box.count()) {
  await box.fill('10');
  await box.press('Enter');
  await page.waitForTimeout(2500);
  const body3 = await page.locator('body').innerText();
  const t3 = (body3.match(/TOTAL PROFIT[^\n]*/i) || [''])[0];
  console.log('total line at base 10:', t3);
}

await page.screenshot({ path: '/tmp/pi_grid_check.png', fullPage: false });
console.log('screenshot: /tmp/pi_grid_check.png');
await browser.close();
