import { chromium } from 'playwright';
const api = async (p) => (await fetch('http://localhost:8503' + p)).json();
const b = await chromium.launch();
const page = await b.newPage({ viewport: { width: 1600, height: 1100 } });
const errors = []; page.on('pageerror', e => errors.push(e.message));
page.on('dialog', d => d.dismiss());
await page.goto('http://localhost:8503/backtest', { waitUntil: 'domcontentloaded' });
await page.waitForSelector('text=UPDATE BACKTEST', { timeout: 60000 });
await page.waitForTimeout(5000);
const fails = []; const ok = (n,c,d) => { console.log((c?'PASS ':'FAIL ')+n+(d?' — '+d:'')); if(!c) fails.push(n); };
const body = await page.evaluate(() => document.body.innerText);
const j = await api('/api/jobs/btupdate');

ok('a job is running to observe', j.running || j.finished, `running=${j.running}`);
// each labelled bar must match ITS OWN job — the screen shows two, and a
// loose "find any percent" match read the wrong one
const bars = await page.evaluate(() =>
  [...document.querySelectorAll('div')]
    .filter(d => /^(full grid|update)\b/.test(d.innerText.trim()))
    .map(d => d.innerText.trim().replace(/\n/g, " ")));
for (const [label, kind] of [["full grid", "backtest"], ["update", "btupdate"]]) {
  const line = bars.find(b => b.startsWith(label));
  if (!line) { console.log(`   (no ${label} bar on screen)`); continue; }
  const mm = line.match(/(\d+\.\d\d)%/);
  ok(`${label} bar prints two decimals`, !!mm, line.slice(0, 70));
  const job = await api(`/api/jobs/${kind}`);
  if (mm && job.running) {
    const shown = parseFloat(mm[1]);
    const expect = job.pct != null ? job.pct : (100 * (job.done ?? 0)) / (job.total || 1);
    ok(`${label} percent matches its own job`, Math.abs(shown - expect) < 6,
       `page ${shown}% vs ${kind} ${expect.toFixed(2)}%`);
    ok(`${label} still shows counts`, line.includes(`${job.done}/${job.total}`),
       `${job.done}/${job.total}`);
  }
}
ok('exactly two decimals, not one or three', !/\d+\.\d%|\d+\.\d{3}%/.test(body));
ok('no js errors', errors.length === 0, errors[0] ?? '');
await page.screenshot({ path: '/tmp/pct2dp.png', fullPage: false });
console.log(fails.length ? 'RESULT: FAIL ' + fails.join(', ') : 'RESULT: ALL PASS');
await b.close();
