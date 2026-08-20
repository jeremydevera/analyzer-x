import { chromium } from 'playwright';
const api = async (p) => (await fetch('http://localhost:8787' + p)).json();
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1680, height: 1200 } });
const errors = []; page.on('pageerror', e => errors.push(e.message));
page.on('dialog', d => d.dismiss());
await page.goto('http://localhost:3000/models', { waitUntil: 'networkidle' });
await page.waitForTimeout(3000);
const fails = []; const ok = (n,c,d) => { console.log((c?'PASS ':'FAIL ')+n+(d?' — '+d:'')); if(!c) fails.push(n); };
const m = await api('/api/models');
let body = await page.evaluate(() => document.body.innerText);

ok('model count derived', body.includes(`${m.rows.length} models`), `api=${m.rows.length}`);
ok('custom count derived', body.includes(`${m.rows.filter(r=>r.custom).length} added by you`));
ok('none tested yet, said plainly', body.includes('none tested yet this visit'));
for (const r of m.rows.slice(0,3)) ok(`row ${r.id}`, body.includes(r.id));
const keyed = m.rows.find(r => r.key_env && r.key_present);
if (keyed) ok('key presence labelled, value absent', body.includes(`${keyed.key_env} set`) && !body.includes(process.env.GOOGLE_API_KEY ?? '@@none@@'));

// live: press one row's test button, assert the badge matches a real ping
const first = m.rows[0].id;
const row = page.locator('tr').filter({ hasText: first });
await row.locator('button', { hasText: 'test' }).first().click();
let badge = '';
for (let i = 0; i < 20; i++) {
  await page.waitForTimeout(1500);
  body = await page.evaluate(() => document.body.innerText);
  const mm = body.match(/(\d+)% (ok|ratelimit|auth|error|degraded)/);
  if (mm) { badge = mm[0]; break; }
}
ok('health badge appeared after test', !!badge, badge);
ok('tested count line updated', /\d+ of \d+ tested are usable now/.test(body));
ok('latency shown in ms', /\d+ ms/.test(body));
ok('no js errors', errors.length === 0, errors[0] ?? '');
await page.screenshot({ path: '/tmp/react-models.png', fullPage: false });
console.log(fails.length ? 'RESULT: FAIL ' + fails.join(', ') : 'RESULT: ALL PASS');
await browser.close();
