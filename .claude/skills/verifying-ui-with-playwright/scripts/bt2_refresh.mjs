import { chromium } from 'playwright';
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1680, height: 1050 } });
await p.goto('http://localhost:8503', { waitUntil: 'networkidle' });
await p.waitForTimeout(8000);
await p.locator('text=Backtest 2').first().click();
await p.waitForTimeout(6000);
// keep it small so the run finishes quickly: 1 coin, 1 timeframe
const tfBox = p.locator('[data-testid="stMultiSelect"]').nth(1);
for (let i = 0; i < 4; i++) { const x = tfBox.locator('span[role="presentation"], [aria-label*="lear"]'); }
await p.locator('[data-testid="stButton"] button').filter({ hasText: /RUN THE DAILY GRID/ }).click();
await p.waitForTimeout(9000);
let body = await p.locator('body').innerText();
console.log('after start, running text present:', /Running detached|working|fetching|combinations|elapsed/i.test(body));
console.log('  line:', (body.match(/(Running detached[^\n]*|[^\n]*elapsed[^\n]*)/)||['-'])[0].slice(0,120));
// THE TEST: full page reload mid-run
await p.reload({ waitUntil: 'networkidle' });
await p.waitForTimeout(9000);
await p.locator('text=Backtest 2').first().click();
await p.waitForTimeout(8000);
body = await p.locator('body').innerText();
const survived = /elapsed|Running detached|OPEN THE DAILY GRID|combinations/i.test(body);
console.log('AFTER REFRESH, progress or result still shown:', survived);
console.log('  line:', (body.match(/([^\n]*elapsed[^\n]*|OPEN THE DAILY GRID[^\n]*)/)||['-'])[0].slice(0,140));
await p.screenshot({ path: '/tmp/bt2_refresh.png' });
await b.close();
