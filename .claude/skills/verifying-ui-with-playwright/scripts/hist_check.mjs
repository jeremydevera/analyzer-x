import { chromium } from 'playwright';
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1920, height: 1050 } });
await page.goto('http://localhost:8503', { waitUntil: 'networkidle' });
await page.waitForTimeout(8000);
await page.locator('text=Auto Trade').first().click();
await page.waitForTimeout(25000);
const hits = await page.locator('text=/trade history/i').count();
console.log('history heading found:', hits);
if (hits) {
  const el = page.locator('text=/trade history/i').first();
  await el.scrollIntoViewIfNeeded();
  const box = await el.boundingBox();
  console.log('y position:', box && Math.round(box.y));
  await page.waitForTimeout(1500);
}
await page.screenshot({ path: '/tmp/hist.png', fullPage: false });
await browser.close();
