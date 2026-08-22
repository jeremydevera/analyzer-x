import { chromium } from 'playwright';
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1680, height: 1050 } });
await p.goto('http://localhost:8507', { waitUntil: 'networkidle' });
await p.waitForTimeout(6000);
await p.locator('text=Backtest 2').first().click();
await p.waitForTimeout(38000);
const link = p.locator('a.bt-open');
const n = await link.count();
console.log('OPEN link present on cold load:', n > 0);
if (n) {
  console.log('  href:', await link.first().getAttribute('href'));
  console.log('  note:', (await link.first().evaluate(e => e.nextElementSibling?.textContent || '')).slice(0, 120));
}
await p.screenshot({ path: '/tmp/bt2_done.png' });
await b.close();
