import { chromium } from 'playwright';
const api = async (p) => (await fetch('http://localhost:8503' + p)).json();
const b = await chromium.launch();
const page = await b.newPage({ viewport: { width: 1600, height: 1100 } });
const errors = []; page.on('pageerror', e => errors.push(e.message));
page.on('dialog', d => d.dismiss());
await page.goto('http://localhost:8503/trade', { waitUntil: 'domcontentloaded' });
await page.waitForSelector('text=FUTURES WALLET', { timeout: 60000 });
await page.waitForTimeout(6000);
const fails = []; const ok = (n,c,d) => { console.log((c?'PASS ':'FAIL ')+n+(d?' — '+d:'')); if(!c) fails.push(n); };
const body = await page.evaluate(() => document.body.innerText);
const sup = await api('/api/trade/supervisor');
const s = await api('/api/trade/summary');

ok('auto-restart switch present', body.includes('auto-restart'));
const cb = page.getByRole('checkbox', { name: 'auto-restart' });
const checked = await page.evaluate(() => {
  const l = [...document.querySelectorAll('label')].find(l => /auto-restart/.test(l.textContent));
  return l?.querySelector('input')?.checked;
});
ok('switch reflects the real agent', checked === sup.installed, `ui=${checked} agent=${sup.installed}`);
ok('runner shown as alive', s.pid ? body.includes(`pid ${s.pid}`) : true, `pid ${s.pid}`);
ok('no DIED badge while it is up', s.pid ? !body.includes('DIED') : true);
ok('no stale-heartbeat badge', !sup.stale ? !body.includes('no heartbeat for') : true, `beat ${sup.last_beat_seconds}s`);
ok('no disk warning while there is room', sup.disk_ok ? !body.includes('disk almost full') : body.includes('disk almost full'),
   `${sup.free_mb} MB free`);
ok('no js errors', errors.length === 0, errors[0] ?? '');
await page.screenshot({ path: '/tmp/runner-health.png', fullPage: false });
console.log(fails.length ? 'RESULT: FAIL ' + fails.join(', ') : 'RESULT: ALL PASS');
await b.close();
