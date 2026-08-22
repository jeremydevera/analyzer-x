import { chromium } from 'playwright';
const U = 'http://localhost:8507';
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1680, height: 1050 } });
const openTab = async () => {
  await p.goto(U, { waitUntil: 'networkidle' });
  await p.waitForTimeout(6000);
  await p.locator('text=Backtest 2').first().click();
  await p.waitForTimeout(38000);
};
await openTab();
// pick ONE coin so the run is quick, and trim to one timeframe
const coinBox = p.locator('[data-testid="stMultiSelect"]').nth(7);
await coinBox.locator('input').first().click();
await p.keyboard.type('XAUT_USDT');
await p.waitForTimeout(1500);
await p.keyboard.press('Enter');
await p.waitForTimeout(6000);
const btn = p.locator('[data-testid="stButton"] button').filter({ hasText: /RUN THE DAILY GRID/ });
console.log('button count:', await btn.count(), '| disabled:', await btn.first().isDisabled());
await btn.first().click();
await p.waitForTimeout(12000);
let t = await p.locator('body').innerText();
console.log('STARTED:', /Started in the background|elapsed|Running detached/i.test(t));
console.log('  ->', (t.match(/[^\n]*(elapsed|background)[^\n]*/i)||['-'])[0].slice(0,130));
await p.reload({ waitUntil: 'networkidle' });          // <-- THE TEST
await p.waitForTimeout(6000);
await p.locator('text=Backtest 2').first().click();
await p.waitForTimeout(38000);
t = await p.locator('body').innerText();
const ok = /elapsed|Running detached|OPEN THE DAILY GRID/i.test(t);
console.log('AFTER FULL REFRESH, still there:', ok);
console.log('  ->', (t.match(/[^\n]*(elapsed|OPEN THE DAILY GRID)[^\n]*/i)||['-'])[0].slice(0,150));
await p.screenshot({ path: '/tmp/bt2_final.png' });
await b.close();
