import { chromium } from 'playwright';
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1680, height: 1050 } });
await p.goto('http://localhost:8507', { waitUntil: 'networkidle' });   // cold load == refresh
await p.waitForTimeout(6000);
await p.locator('text=Backtest 2').first().click();
await p.waitForTimeout(38000);
const t = await p.locator('body').innerText();
const line = (t.match(/[^\n]*(OPEN THE DAILY GRID|combinations)[^\n]*/i)||['NOT FOUND'])[0];
console.log('progress visible on a COLD load:', /OPEN THE DAILY GRID|combinations/i.test(t));
console.log('  ->', line.trim().slice(0, 150));
console.log('says detached:', /Running detached/i.test(t));
await p.screenshot({ path: '/tmp/bt2_disk.png' });
await b.close();
