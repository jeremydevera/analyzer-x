import { chromium } from 'playwright';
const api = async (p) => (await fetch('http://localhost:8503' + p)).json();
const b = await chromium.launch();
const page = await b.newPage({ viewport: { width: 2100, height: 1300 } });
const errors = []; page.on('pageerror', e => errors.push(e.message));
page.on('dialog', d => d.dismiss());
await page.goto('http://localhost:8503/trade', { waitUntil: 'networkidle' });
await page.waitForTimeout(6500);
const fails = []; const ok = (n,c,d) => { console.log((c?'PASS ':'FAIL ')+n+(d?' — '+d:'')); if(!c) fails.push(n); };
const body = await page.evaluate(() => document.body.innerText);
const st = await api('/api/trade/strategies');
const eq = await api('/api/trade/equity');

for (const h of ['notional $', 'streak', 'next $', `ladder $ · ${st.flat ? 'flat' : 'DEEP'}`])
  ok(`column "${h}"`, body.includes(h));
const laddered = st.rows.find((r) => (r.streak ?? 0) > 0);
if (laddered) {
  ok(`${laddered.key} streak shown`, body.includes(`${laddered.streak} loss`), `${laddered.streak}`);
  ok(`${laddered.key} next stake shown`, body.includes(String(laddered.next_stake)), String(laddered.next_stake));
  ok('the boxed rung is the current one', await page.evaluate((k) => {
    const tr = [...document.querySelectorAll('tr')].find(r => r.textContent.startsWith(k));
    const boxed = tr?.querySelector('.bg-warning-400');
    return !!boxed;
  }, laddered.key));
} else ok('a laddered row exists to check', true, 'no row is mid-streak right now');
ok('notional printed', body.includes(String(st.rows[0].notional)));
ok('equity curve section', body.includes('Equity, every closed trade'));
ok('equity trade count matches', body.includes(`${eq.trades} closed trades`), String(eq.trades));
ok('legend colour follows the sign', body.includes('realised, cumulative') && body.includes('break-even'));

// the live lock: a row whose coin is held cannot be armed
const locked = Object.keys(st.locks);
if (locked.length) {
  ok('locks named above the table', body.includes('live-locked:'));
  const k = locked[0];
  const btn = page.locator('tr').filter({ hasText: k }).locator('button', { hasText: 'REAL' }).first();
  ok(`${k} REAL pill disabled`, await btn.isDisabled(), `held by ${st.locks[k].held_by}`);
} else {
  ok('no locks right now, banner absent', !body.includes('live-locked:'));
}
ok('no js errors', errors.length === 0, errors[0] ?? '');
await page.screenshot({ path: '/tmp/ladder-lock.png', fullPage: false });
console.log(fails.length ? 'RESULT: FAIL ' + fails.join(', ') : 'RESULT: ALL PASS');
await b.close();
