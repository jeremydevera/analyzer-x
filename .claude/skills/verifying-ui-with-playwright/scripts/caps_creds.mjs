import { chromium } from 'playwright';
const api = async (p) => (await fetch('http://localhost:8503' + p)).json();
const b = await chromium.launch();
const page = await b.newPage({ viewport: { width: 1920, height: 1300 } });
const errors = []; page.on('pageerror', e => errors.push(e.message));
const dialogs = []; page.on('dialog', d => { dialogs.push(d.message()); d.dismiss(); });
await page.goto('http://localhost:8503/trade', { waitUntil: 'networkidle' });
await page.waitForTimeout(6000);
const fails = []; const ok = (n,c,d) => { console.log((c?'PASS ':'FAIL ')+n+(d?' — '+d:'')); if(!c) fails.push(n); };
const body = await page.evaluate(() => document.body.innerText);
const st = await api('/api/trade/strategies');
const cr = await api('/api/trade/credentials');

// loss caps
ok('per-strategy loss cap column', body.includes('loss cap $'));
ok('today $ column', body.includes('today $'));
ok('account loss cap control', body.includes('account loss cap $ (0 = off)'));
ok('cap-hit banner matches reality', st.account_cap_hit ? body.includes('has been reached today') : !body.includes('has been reached today'));
ok('paused banner matches reality', st.tripped.length ? body.includes('Paused for the rest of today') : !body.includes('Paused for the rest of today'));

// credentials
ok('keys panel present', body.includes('MEXC keys'));
ok('source named', body.includes(cr.source), cr.source);
ok('key shown MASKED only', body.includes(cr.key_fingerprint.split('  ')[0].slice(-4)) && body.includes('•'));
ok('store path + permissions shown', body.includes(cr.store_path) && body.includes(cr.file_mode));
ok('permissions verdict derived', cr.file_mode_ok ? body.includes('only you can read it') : body.includes('readable by others'));
ok('inputs are password type', (await page.locator('input[type="password"]').count()) === 2);
ok('SAVE disabled while empty', await page.locator('button', { hasText: 'SAVE KEYS' }).first().isDisabled());
ok('FORGET asks first', true);   // checked below

// real preflight against MEXC
await page.locator('button', { hasText: 'TEST CONNECT' }).first().click();
let probed = false, out = '';
for (let i = 0; i < 20; i++) {
  await page.waitForTimeout(1500);
  out = await page.evaluate(() => document.body.innerText);
  if (/PASS|FAIL|UNKNOWN/.test(out) && out.includes('Rest a stop')) { probed = true; break; }
}
ok('TEST CONNECT reports the five checks', probed);
for (const label of ['Credentials present','Read account balance','Read open positions','Permission to place orders',"Rest a stop on MEXC's servers"])
  ok(`check "${label}"`, out.includes(label));
await page.locator('button', { hasText: 'FORGET SAVED KEYS' }).first().click();
await page.waitForTimeout(700);
ok('forget asks before deleting', dialogs.some(m => /Forget the saved keys/i.test(m)));
ok('no js errors', errors.length === 0, errors[0] ?? '');
await page.screenshot({ path: '/tmp/caps-creds.png', fullPage: false });
console.log(fails.length ? 'RESULT: FAIL ' + fails.join(', ') : 'RESULT: ALL PASS');
await b.close();
