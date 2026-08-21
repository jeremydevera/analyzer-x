import { chromium } from 'playwright';
const RID = process.argv[2];
const api = async (p) => (await fetch('http://localhost:8503' + p)).json();
const b = await chromium.launch();
const page = await b.newPage({ viewport: { width: 1680, height: 1200 } });
const errors = []; page.on('pageerror', e => errors.push(e.message));
page.on('dialog', d => d.dismiss());
await page.goto('http://localhost:8503/analysis', { waitUntil: 'networkidle' });
await page.waitForTimeout(4000);
const fails = []; const ok = (n,c,d) => { console.log((c?'PASS ':'FAIL ')+n+(d?' — '+d:'')); if(!c) fails.push(n); };
let body = await page.evaluate(() => document.body.innerText);

// curated tickers reach the picker
const tk = await api('/api/analysis/tickers');
const opts = await page.locator('#ta-tickers option').count();
ok('ticker list wired', opts === tk.rows.length, `${opts} of ${tk.rows.length}`);

// parallel mode
ok('parallel toggle', body.includes('parallel — compare models'));
await page.getByText('parallel — compare models').locator('..').locator('input[type="checkbox"]').check();
await page.waitForTimeout(700);
body = await page.evaluate(() => document.body.innerText);
ok('multi-select appears', body.includes('models to compare'));
ok('own-provider reason stated', body.includes('separate rate-limit quotas'));
const startBtn = page.locator('button', { hasText: /^START/ }).first();
ok('start disabled under two models', await startBtn.isDisabled());
await page.locator('input[list="ta-tickers"]').first().fill('AAPL');   // the button also needs a ticker
await page.locator('select[multiple]').first().selectOption([{ index: 0 }, { index: 1 }]);
await page.waitForTimeout(500);
body = await page.evaluate(() => document.body.innerText);
ok('button counts the runs', body.includes('START 2 RUNS'));
ok('start enabled with two', !(await startBtn.isDisabled()));

// the finished parallel run: open it and check the export
await page.locator('button', { hasText: RID }).first().click();
await page.waitForTimeout(3500);
body = await page.evaluate(() => document.body.innerText);
const r = await api(`/api/analysis/${RID}`);
ok('run opens with its stages', body.includes(`${r.stages.filter(s=>s.status==='done').length}/${r.stages.length} stages`));
const dl = page.locator('a', { hasText: 'DOWNLOAD .md' }).first();
ok('download link present', await dl.count() > 0);
const href = await dl.getAttribute('href');
ok('download points at the run', href.includes(`/api/analysis/${RID}/report.md`), href);
// href is same-origin and relative; make it absolute for the request API
const resp = await page.request.get(new URL(href, 'http://localhost:8503').toString());
const md = await resp.text();
ok('markdown carries the sections', md.includes('## Market Analyst') && md.includes('## Final decision'));
ok('markdown names the model', md.includes(r.spec.model), r.spec.model);
ok('no js errors', errors.length === 0, errors[0] ?? '');
await page.screenshot({ path: '/tmp/analysis2.png', fullPage: false });
console.log(fails.length ? 'RESULT: FAIL ' + fails.join(', ') : 'RESULT: ALL PASS');
await b.close();
