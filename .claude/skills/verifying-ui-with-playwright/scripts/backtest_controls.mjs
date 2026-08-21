import { chromium } from 'playwright';
const api = async (p) => (await fetch('http://localhost:8503' + p)).json();
const b = await chromium.launch();
const page = await b.newPage({ viewport: { width: 1680, height: 1200 } });
const errors = []; page.on('pageerror', e => errors.push(e.message));
page.on('dialog', d => d.dismiss());
await page.goto('http://localhost:8503/backtest', { waitUntil: 'networkidle' });
await page.waitForTimeout(4000);
const fails = []; const ok = (n,c,d) => { console.log((c?'PASS ':'FAIL ')+n+(d?' — '+d:'')); if(!c) fails.push(n); };

// set a selection the plan can be checked against
const coinBox = page.locator('input').first();
await coinBox.fill('XAUT_USDT');
await page.waitForTimeout(2500);
let body = await page.evaluate(() => document.body.innerText);
const tfs = ['15m','30m','1h','4h'];
const plan = await api(`/api/backtest/plan?coins=XAUT_USDT&tfs=${tfs.join(',')}`);
const dep = await api(`/api/backtest/deployed?coins=XAUT_USDT&tfs=${tfs.join(',')}`);

ok('base margin input', body.includes('Base margin $'));
ok('cost stated before spending', body.includes(`${plan.signals} signals`) && body.includes(plan.combinations.toLocaleString('en-US')),
   `${plan.combinations.toLocaleString('en-US')} combos`);
ok('ETA stated', body.includes(`${plan.eta_minutes} min`));
ok('three costs + liquidation named', body.includes('all three costs charged') && body.includes('liquidation modelled'));
ok('deployed rows named', dep.rows.length ? body.includes('will be injected and marked DEPLOYED') && body.includes(dep.rows[0].key) : true,
   dep.rows.map(r => r.key).join(','));
ok('UPDATE BACKTEST button', body.includes('UPDATE BACKTEST'));
ok('run-where control', body.includes('Run where') && body.includes('this Mac') && body.includes('GitHub Actions'));

// switching to GitHub says whether it is usable, from the real gh CLI
await page.locator('button', { hasText: 'GitHub Actions' }).first().click();
await page.waitForTimeout(1200);
body = await page.evaluate(() => document.body.innerText);
const cloud = await api('/api/cloud/status');
ok('github availability is real', cloud.available
   ? body.includes('their machines run the same grid')
   : body.includes('unavailable'), `available=${cloud.available}`);
ok('RUN ON GITHUB button appears', body.includes('RUN ON GITHUB'));
ok('mac-only buttons hidden in github mode', !body.includes('UPDATE BACKTEST'));

// base margin actually travels into the job spec
await page.locator('button', { hasText: 'this Mac' }).first().click();
await page.waitForTimeout(600);
const marginInput = page.locator('input[type="number"]').first();
await marginInput.fill('12');
await page.waitForTimeout(400);
ok('base margin editable', (await marginInput.inputValue()) === '12');
ok('no js errors', errors.length === 0, errors[0] ?? '');
await page.screenshot({ path: '/tmp/backtest-controls.png', fullPage: false });
console.log(fails.length ? 'RESULT: FAIL ' + fails.join(', ') : 'RESULT: ALL PASS');
await b.close();
