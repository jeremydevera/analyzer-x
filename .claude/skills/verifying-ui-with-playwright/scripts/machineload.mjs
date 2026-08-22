import { chromium } from 'playwright';
const api = async (p) => (await fetch('http://localhost:8503' + p)).json();
const b = await chromium.launch();
const page = await b.newPage({ viewport: { width: 1700, height: 1100 } });
const errors = []; page.on('pageerror', e => errors.push(e.message));
page.on('dialog', d => d.dismiss());
await page.goto('http://localhost:8503/backtest', { waitUntil: 'domcontentloaded' });
await page.waitForSelector('text=UPDATE BACKTEST', { timeout: 60000 });
await page.waitForTimeout(6000);
const fails = []; const ok = (n,c,d) => { console.log((c?'PASS ':'FAIL ')+n+(d?' — '+d:'')); if(!c) fails.push(n); };
const body = await page.evaluate(() => document.body.innerText);
const sys = await api('/api/system');
const job = await api('/api/jobs/backtest');

ok('a job is running to host the readout', job.running, `running=${job.running}`);
ok('CPU busy shown', /CPU \d+\.\d%/.test(body), body.match(/CPU \d+\.\d%/)?.[0]);
ok('load per core shown', /load [\d.]+\/\d+ \([\d.]+x\)/.test(body), body.match(/load [\d.]+\/\d+ \([\d.]+x\)/)?.[0]);
ok('core count is this Mac\'s', body.includes(`/${sys.cores} (`), `${sys.cores} cores`);
const m = body.match(/CPU (\d+\.\d)%/);
if (m) ok('the figure tracks the API', Math.abs(parseFloat(m[1]) - (sys.busy ?? -1)) < 30,
          `page ${m[1]}% vs api ${sys.busy}%`);
// the honest part: no invented temperature
// a real temperature reads "62°C" / "62 °C" / "temp 62" — not "#MBYELQ6C",
// which is a row id and matched my first, looser pattern
ok('no temperature is invented',
   !/\d+\s?°\s?[CF]\b|\btemp(erature)?\s*[:=]?\s*\d+/i.test(body),
   (body.match(/[^\n]*\d+\s?°\s?[CF][^\n]*/i) || [])[0] ?? "none");
ok('it says why there is none', sys.thermal.throttled
   ? body.includes('THROTTLING')
   : body.includes('no throttling') || body.includes('temp: root only'),
   sys.thermal.pressure ?? "unavailable");
ok('no js errors', errors.length === 0, errors[0] ?? '');
await page.screenshot({ path: '/tmp/machineload.png', fullPage: false });
console.log(fails.length ? 'RESULT: FAIL ' + fails.join(', ') : 'RESULT: ALL PASS');
await b.close();
