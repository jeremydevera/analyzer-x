import { chromium } from 'playwright';
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1680, height: 1050 } });
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));

// root must land on /backtest
await page.goto('http://localhost:3000/', { waitUntil: 'networkidle' });
await page.waitForTimeout(2500);
const fails = [];
const ok = (n, c, d) => { console.log((c ? 'PASS ' : 'FAIL ') + n + (d ? ' — ' + d : '')); if (!c) fails.push(n); };
ok('/ redirects to /backtest', page.url().includes('/backtest'), page.url());

await page.waitForTimeout(4000);
const body = await page.evaluate(() => document.body.innerText);
for (const gone of ['TailAdmin', 'Musharof', 'Upgrade To Pro', 'Calendar', 'User Profile', 'Ecommerce', 'UI Elements', 'Sign In', 'Search or type command'])
  ok(`gone: ${gone}`, !body.includes(gone));
for (const there of ['Trading Agents', 'Backtest', 'Stored strategies', 'Size per coin', 'API on localhost:8787'])
  ok(`present: ${there}`, body.includes(there));
ok('API chip up', body.includes('API on localhost:8787') && !body.includes('MB stored'));
ok('no js errors', errors.length === 0, errors[0] ?? '');
await page.screenshot({ path: '/tmp/react-prod.png', fullPage: false });
console.log(fails.length ? 'RESULT: FAIL ' + fails.join(', ') : 'RESULT: ALL PASS');
await browser.close();
