import { chromium } from 'playwright';
const api = async (p) => (await fetch('http://localhost:8503' + p)).json();
const b = await chromium.launch();
const page = await b.newPage({ viewport: { width: 1512, height: 1100 } });
const errors = []; page.on('pageerror', e => errors.push(e.message));
page.on('dialog', d => d.dismiss());
const fails = []; const ok = (n,c,d) => { console.log((c?'PASS ':'FAIL ')+n+(d?' — '+d:'')); if(!c) fails.push(n); };

const bt = await api('/api/jobs/backtest');
const upd = await api('/api/jobs/btupdate');
const ageMin = (j) => j.finished ? Math.round((Date.now()/1000 - j.finished)/60) : null;
console.log(`   (backtest finished ${ageMin(bt)} min ago, stopped=${bt.stopped}; btupdate ${ageMin(upd)} min ago)`);

await page.goto('http://localhost:8503/backtest', { waitUntil: 'domcontentloaded' });
await page.waitForSelector('text=UPDATE BACKTEST', { timeout: 60000 });
await page.waitForTimeout(4000);
const body = await page.evaluate(() => document.body.innerText);

// the RULE, stated directly: no bar on screen may be older than 10 minutes.
// (Checking for a job's note collided with a fresh job carrying the same
// words — "stopped by you" is on screen legitimately when a stop just
// happened.)
const stamps = await page.evaluate(() =>
  [...document.querySelectorAll('p')]
    .filter(p => /clears itself/.test(p.textContent))
    .map(p => (p.textContent.match(/(?:finished|stopped|failed)\s+(.+?)\s+·/) || [])[1])
    .filter(Boolean));
const tooOld = stamps.filter(t => (Date.now() - new Date(t).getTime()) / 60000 > 10);
ok('no bar older than 10 minutes is on screen', tooOld.length === 0,
   `stamps: ${stamps.join(' | ') || 'none'}`);
ok('the 11-hour-old stopped backtest is not shown',
   !stamps.some(t => Math.abs((Date.now() - new Date(t).getTime())/60000 - ageMin(bt)) < 2),
   `bt was ${ageMin(bt)} min old`);
// only STALE results must be absent; a fresh one is news and should show
const live = await Promise.all([api('/api/jobs/backtest'), api('/api/jobs/btupdate')]);
const fresh = live.filter(j => j.running ||
  (j.finished && (Date.now()/1000 - j.finished) < 600)).length;
const bars = await page.evaluate(() =>
  [...document.querySelectorAll('div')].filter(d => /rounded-full bg-(success|warning|error|brand)-/.test(d.className)).length);
ok('bars on screen match only the FRESH jobs', bars === fresh, `${bars} bars, ${fresh} fresh job(s)`);

// the stopped-bar behaviour has its own deterministic script
// (stopped_bar.mjs) — starting and interrupting a job here raced the job's
// own runtime and proved nothing.
ok('no js errors', errors.length === 0, errors[0] ?? '');
console.log(fails.length ? 'RESULT: FAIL ' + fails.join(', ') : 'RESULT: ALL PASS');
await b.close();
