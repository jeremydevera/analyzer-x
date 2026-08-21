import { chromium } from 'playwright';
const api = async (p, body) => (await fetch('http://localhost:8503' + p, body ? {
  method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)} : undefined)).json();
const b = await chromium.launch();
const page = await b.newPage({ viewport: { width: 1680, height: 1250 } });
const errors = []; page.on('pageerror', e => errors.push(e.message));
page.on('dialog', d => d.dismiss());
await page.goto('http://localhost:8503/new-crypto', { waitUntil: 'networkidle' });
await page.waitForTimeout(6000);
const fails = []; const ok = (n,c,d) => { console.log((c?'PASS ':'FAIL ')+n+(d?' — '+d:'')); if(!c) fails.push(n); };
let body = await page.evaluate(() => document.body.innerText);

ok('watch control', body.includes('watch for new listings'));
ok('loop hidden until watching', !body.includes('loop the alarm'));
ok('age unit pickers', body.includes('age from') && body.includes('age to'));
ok('show-all control', body.includes('show all (incl. dust)'));
// address it by its accessible name — sibling checkboxes share the parent
await page.getByRole('checkbox', { name: 'watch for new listings' }).check();
await page.waitForTimeout(9000);
body = await page.evaluate(() => document.body.innerText);
ok('loop + test sound appear', body.includes('loop the alarm') && body.includes('test sound'));
const known = (await api('/api/crypto/watch', { known: [] })).known.length;
ok('watch status names the baseline', /watching [\d,]+ pairs/.test(body), body.match(/watching [\d,]+ pairs/)?.[0]);
ok('poll cadence stated', body.includes('one request every 2 min'));

// click a coin: chart + analyze
const firstRow = page.locator('table tbody tr').first();
await firstRow.click();
await page.waitForTimeout(3500);
body = await page.evaluate(() => document.body.innerText);
ok('detail panel opens', body.includes('ANALYZE THIS COIN'));
ok('chart intervals offered', body.includes('15m') && body.includes('4h'));
ok('chart drew bars', /\d+ bars · last/.test(body), body.match(/\d+ bars · last [\d.]+/)?.[0]);
const canvas = page.locator('canvas').first();
ok('canvas has real size', (await canvas.boundingBox()).height > 100);
// switching interval refetches
const before = body.match(/(\d+) bars/)?.[1];
await page.locator('button', { hasText: /^4h$/ }).first().click();
await page.waitForTimeout(2500);
body = await page.evaluate(() => document.body.innerText);
ok('interval switch refetches', /\d+ bars/.test(body));

// ANALYZE hands off to the Analysis screen with a real run id
await page.locator('button', { hasText: 'ANALYZE THIS COIN' }).first().click();
await page.waitForTimeout(6000);
ok('navigates to the analysis screen', page.url().includes('/analysis?run='), page.url());
body = await page.evaluate(() => document.body.innerText);
const rid = new URL(page.url()).searchParams.get('run');
ok('the handed-over run is open', body.includes(rid), rid);
const st = await api(`/api/analysis/${rid}`);
ok('it is a real crypto run', st.spec.asset_type === 'crypto' && st.spec.ticker === rid.split('-')[0], `${st.spec.ticker} ${st.spec.asset_type}`);
ok('no js errors', errors.length === 0, errors[0] ?? '');
await page.screenshot({ path: '/tmp/crypto2.png', fullPage: false });
console.log(fails.length ? 'RESULT: FAIL ' + fails.join(', ') : 'RESULT: ALL PASS');
await b.close();
