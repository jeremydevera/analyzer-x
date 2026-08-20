import { chromium } from 'playwright';
const api = async (p) => (await fetch('http://localhost:8787' + p)).json();
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1680, height: 1200 } });
const errors = []; page.on('pageerror', e => errors.push(e.message));
await page.goto('http://localhost:3000/new-crypto', { waitUntil: 'networkidle' });
await page.waitForTimeout(6000);
const fails = []; const ok = (n,c,d) => { console.log((c?'PASS ':'FAIL ')+n+(d?' — '+d:'')); if(!c) fails.push(n); };
const d = await api('/api/crypto/new');
const body = await page.evaluate(() => document.body.innerText);

ok('window in heading', body.includes(`last ${d.window_days} days`));
ok('shown-of-scanned line', body.includes(`${d.rows.length} shown of ${d.scanned.toLocaleString('en-US')} USDT pairs scanned`),
   `${d.rows.length}/${d.scanned}`);
ok('cache provenance stated', /(cached|fresh) sweep from/.test(body) || body.includes('STALE'));
if (d.unresolved) ok('undated coins declared', body.includes(`${d.unresolved} could NOT be dated`));
if (d.hidden_by_volume) ok('volume-hidden declared', body.includes(`${d.hidden_by_volume} hidden by volume`));
// row content matches the API row-for-row on the first few
for (const c of d.rows.slice(0, 3)) {
  const pct = `${c.change_pct >= 0 ? '+' : ''}${c.change_pct.toFixed(2)}%`;
  ok(`row ${c.base}`, body.includes(c.base) && body.includes(c.listed_date) && body.includes(pct), pct);
}
// sorting works on a real column
const rowsBefore = await page.locator('table tbody tr').first().innerText();
await page.locator('button', { hasText: /^24h volume \$/ }).first().click();
await page.waitForTimeout(600);
const rowsAfter = await page.locator('table tbody tr').first().innerText();
ok('sort by volume changes the top row', rowsBefore !== rowsAfter, `${rowsBefore.split('\n')[0]} → ${rowsAfter.split('\n')[0]}`);
const up = await api('/api/crypto/upcoming');
ok('upcoming section present', body.includes('Announced, not trading yet'));
ok('upcoming count derived', up.why ? body.includes('schedule unavailable') : body.includes(`${up.rows.length} listing`));
ok('no js errors', errors.length === 0, errors[0] ?? '');
await page.screenshot({ path: '/tmp/react-crypto.png', fullPage: false });
console.log(fails.length ? 'RESULT: FAIL ' + fails.join(', ') : 'RESULT: ALL PASS');
await browser.close();
