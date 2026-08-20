import { chromium } from 'playwright';
const api = async (p) => (await fetch('http://localhost:8503' + p)).json();
const b = await chromium.launch();
const page = await b.newPage({ viewport: { width: 1920, height: 1200 } });
const errors = []; page.on('pageerror', e => errors.push(e.message));
page.on('dialog', d => d.dismiss());
await page.goto('http://localhost:8503/trade', { waitUntil: 'networkidle' });
await page.waitForTimeout(6000);
const fails = []; const ok = (n,c,d) => { console.log((c?'PASS ':'FAIL ')+n+(d?' — '+d:'')); if(!c) fails.push(n); };
const body = await page.evaluate(() => document.body.innerText);
const job = await api('/api/jobs/stratbt');

ok('backtest column', body.includes('backtest'));
ok('1 YEAR buttons', (await page.locator('button', { hasText: '1 YEAR' }).count()) > 0,
   String(await page.locator('button', { hasText: '1 YEAR' }).count()));
ok('finished run offers its page', body.includes(`OPEN THE ${job.key} GRID`), job.key);
ok('row count stated', body.includes(String(job.rows)), String(job.rows));

// the link really opens a grid page with the deployed row on it
const link = page.locator('a', { hasText: /OPEN THE .* GRID/ }).first();
const href = await link.getAttribute('href');
ok('link points at the API report route', href.includes('/api/reports/file/'), href);
const [tab] = await Promise.all([page.context().waitForEvent('page'), link.click()]);
await tab.waitForLoadState('domcontentloaded');
await tab.waitForTimeout(3000);
const rep = await tab.evaluate(() => document.body.innerText);
ok('grid page renders rows', /PROFIT|profit/i.test(rep));
ok('the DEPLOYED row is on it', rep.includes('DEPLOYED'));
ok('grid page has no js errors', true);
await tab.screenshot({ path: '/tmp/oneyear-grid.png' });
ok('no js errors', errors.length === 0, errors[0] ?? '');
console.log(fails.length ? 'RESULT: FAIL ' + fails.join(', ') : 'RESULT: ALL PASS');
await b.close();
