import { chromium } from 'playwright';
const api = async (p) => (await fetch('http://localhost:8503' + p)).json();
const b = await chromium.launch();
const page = await b.newPage({ viewport: { width: 1680, height: 1250 } });
const errors = []; page.on('pageerror', e => errors.push(e.message));
page.on('dialog', d => d.dismiss());
await page.goto('http://localhost:8503/trade', { waitUntil: 'networkidle' });
await page.waitForTimeout(5000);
const fails = []; const ok = (n,c,d) => { console.log((c?'PASS ':'FAIL ')+n+(d?' — '+d:'')); if(!c) fails.push(n); };
let body = await page.evaluate(() => document.body.innerText);
const d = await api('/api/trade/strategies');

ok('heading says DEPLOYED, not all', body.includes('Strategies you have deployed'));
ok('real count leads the caption', body.includes(`${d.real_count} trading REAL money`), `${d.real_count}`);
ok('paper count stated', body.includes(`${d.paper_count} paper only`));
ok('catalog count NOT presented as active', !body.includes(`${d.catalog_count} configured`));
// exactly the deployed keys are on screen, and no others
for (const r of d.rows) ok(`row ${r.key} shown`, body.includes(r.key));
const catalogOnly = ['ict_fvg','sweep_rt','fade15_1m','mom15_sp','rsi14_1h'];
for (const k of catalogOnly) ok(`${k} hidden until asked`, !body.includes(k));
ok('ARMED badges = real-armed rows', (body.match(/ARMED/g) || []).length === d.real_count, `${(body.match(/ARMED/g)||[]).length} vs ${d.real_count}`);

// the catalog is reachable, and switching to it says so
// by accessible name: .first() became "arm PANIC" once that control landed
await page.getByRole('checkbox', { name: /show all \d+ to arm a new one/ }).check();
await page.waitForTimeout(2500);
body = await page.evaluate(() => document.body.innerText);
ok('catalog toggle reveals the rest', body.includes('every configurable one') && body.includes('ict_fvg'));
ok('counts still describe what is deployed', body.includes(`${d.real_count} trading REAL money`));
ok('no js errors', errors.length === 0, errors[0] ?? '');
await page.screenshot({ path: '/tmp/armed-only.png', fullPage: false });
console.log(fails.length ? 'RESULT: FAIL ' + fails.join(', ') : 'RESULT: ALL PASS');
await b.close();
