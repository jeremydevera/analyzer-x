import { chromium } from 'playwright';
const RID = process.argv[2];
const api = async (p) => (await fetch('http://localhost:8787' + p)).json();
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1680, height: 1200 } });
const errors = []; page.on('pageerror', e => errors.push(e.message));
page.on('dialog', d => d.dismiss());
await page.goto('http://localhost:3000/analysis', { waitUntil: 'networkidle' });
await page.waitForTimeout(3000);
const fails = []; const ok = (n,c,d) => { console.log((c?'PASS ':'FAIL ')+n+(d?' — '+d:'')); if(!c) fails.push(n); };
let body = await page.evaluate(() => document.body.innerText);

const runs = await api('/api/analysis/runs');
ok('recent runs count derived', body.includes(`${runs.rows.length} on this Mac`), `${runs.rows.length}`);
ok('finished run listed', body.includes(RID), RID);

// open the finished run: stages, reports, decision must match the API
await page.locator('button', { hasText: RID }).first().click();
await page.waitForTimeout(3000);
body = await page.evaluate(() => document.body.innerText);
const r = await api(`/api/analysis/${RID}`);
const done = r.stages.filter(s => s.status === 'done').length;
ok('stage count label', body.includes(`finished · ${done}/${r.stages.length} stages`), `${done}/${r.stages.length}`);
for (const s of r.stages) ok(`stage ${s.label}`, body.includes(s.label));
const nrep = Object.keys(r.reports).length;
ok('report count derived', body.includes(`${nrep} reports written so far`) || body.includes(`${nrep} report written so far`), `${nrep}`);
// innerText returns the RENDERED case, and this heading is uppercase in CSS
ok('final decision shown', !!r.decision && /final decision/i.test(body));
ok('decision text is the run\'s own', body.includes(r.decision.trim().slice(0, 30)));
// expand one report and check its text really came from the run
const label = Object.keys(r.reports)[0];
await page.locator('button', { hasText: label }).first().click();
await page.waitForTimeout(800);
body = await page.evaluate(() => document.body.innerText);
const head = r.reports[label].trim().slice(0, 40);
ok('report body matches the API text', body.includes(head), head.slice(0, 30));
ok('no js errors', errors.length === 0, errors[0] ?? '');
await page.screenshot({ path: '/tmp/react-analysis.png', fullPage: false });
console.log(fails.length ? 'RESULT: FAIL ' + fails.join(', ') : 'RESULT: ALL PASS');
await browser.close();
