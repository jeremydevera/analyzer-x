import { chromium } from 'playwright';
const api = async (p) => (await fetch('http://localhost:8503' + p)).json();
const b = await chromium.launch();
const page = await b.newPage({ viewport: { width: 1700, height: 1200 } });
const errors = []; page.on('pageerror', e => errors.push(e.message));
page.on('dialog', d => d.dismiss());
await page.goto('http://localhost:8503/backtest', { waitUntil: 'domcontentloaded' });
await page.waitForSelector('text=UPDATE BACKTEST', { timeout: 60000 });
await page.waitForTimeout(5000);
const fails = []; const ok = (n,c,d) => { console.log((c?'PASS ':'FAIL ')+n+(d?' — '+d:'')); if(!c) fails.push(n); };
const body = await page.evaluate(() => document.body.innerText);
const j = await api('/api/jobs/backtest');
const ws = j.workers ?? [];

ok('a sweep is running with cores', j.running && ws.length > 0, `${ws.length} of ${j.cores}`);
// workers finish pairs constantly, so the live count moves between the render
// and this sample; what must hold is the SHAPE and the ceiling
// innerText returns the RENDERED case and this heading is uppercase in CSS
const cm = body.match(/(\d+) OF (\d+) CORES? WORKING/i);
ok('the count line names live cores of the total', !!cm, cm?.[0] ?? "no count line");
if (cm) {
  ok('it never claims more cores than the sweep was given',
     Number(cm[1]) <= Number(cm[2]) && Number(cm[2]) === j.cores, cm[0]);
  ok('it is within a worker of the sampled truth',
     Math.abs(Number(cm[1]) - ws.length) <= 2, `page ${cm[1]} vs api ${ws.length}`);
}
// every core row shows two decimals
const rows = await page.evaluate(() => {
  const head = [...document.querySelectorAll('p')].find(p => /cores working/i.test(p.textContent));
  const box = head?.parentElement;
  return [...(box?.querySelectorAll(':scope > div > div') ?? [])].map(d => d.innerText.replace(/\n/g, " "));
});
ok('a row per living core', rows.length === ws.length, `${rows.length} rows vs ${ws.length} workers`);
// a core between pairs prints "saving" (it is writing 17 MB of rows), which
// is a state, not a percentage — every OTHER row must carry two decimals
const pctRows = rows.filter((r) => !/saving/.test(r));
const twoDp = pctRows.filter((r) => /\d+\.\d\d%/.test(r));
ok('every working core shows two decimals', twoDp.length === pctRows.length,
   pctRows.find((r) => !/\d+\.\d\d%/.test(r)) ?? `${pctRows.length} rows`);
ok('no row claims "done" while the sweep runs',
   !rows.some((r) => /\bdone\b/.test(r)), rows.find((r) => /\bdone\b/.test(r)) ?? "none");
// each row's pair and percent match its own worker
// A core swaps to its next pair every few seconds, so demanding that EVERY
// sampled worker is on the rendered page tests the clock, not the panel. For
// the ones present in both, the figure must agree — and at least one must be,
// or this check proves nothing.
let matched = 0;
for (const w of ws) {
  const row = rows.find((r) => r.includes(w.pair));
  if (!row || /saving/.test(row)) continue;
  matched += 1;
  const shown = parseFloat((row.match(/(\d+\.\d\d)%/) || [])[1] ?? "-1");
  ok(`core ${w.core} (${w.pair}) percent matches`, Math.abs(shown - (w.pct ?? 0)) < 12,
     `page ${shown}% vs worker ${w.pct}%`);
}
ok('at least one core was cross-checked', matched > 0, `${matched} of ${ws.length}`);
ok('no js errors', errors.length === 0, errors[0] ?? '');
await page.screenshot({ path: '/tmp/cores.png', fullPage: false });
console.log(fails.length ? 'RESULT: FAIL ' + fails.join(', ') : 'RESULT: ALL PASS');
await b.close();
