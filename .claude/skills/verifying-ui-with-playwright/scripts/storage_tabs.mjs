import { chromium } from 'playwright';
const api = async (p) => (await fetch('http://localhost:8503' + p)).json();
const b = await chromium.launch();
const page = await b.newPage({ viewport: { width: 1512, height: 1200 } });
const errors = []; page.on('pageerror', e => errors.push(e.message));
page.on('dialog', d => d.dismiss());
await page.goto('http://localhost:8503/candles', { waitUntil: 'domcontentloaded' });
await page.waitForSelector('text=Size per coin', { timeout: 60000 });
await page.waitForTimeout(4000);
const fails = []; const ok = (n,c,d) => { console.log((c?'PASS ':'FAIL ')+n+(d?' — '+d:'')); if(!c) fails.push(n); };
let body = await page.evaluate(() => document.body.innerText);
const st = (await api('/api/storage/by-coin')).rows;
const mb = (b) => `${(b/1e6).toFixed(2)} MB`;
const tfs = [...new Set(st.map(r => r.tf))].sort();

// --- last updated column
ok('last updated column', body.includes('last updated'));
ok('bars column', body.includes('bars'));
const withStamp = st.filter(r => r.last_ms).length;
ok('the store really has stamps', withStamp > 0, `${withStamp}/${st.length} pairs`);
ok('an age is printed', /\d+[mhd] (\d+[mh] )?ago/.test(body), body.match(/\d+[mhd] (\d+[mh] )?ago/)?.[0]);

// --- tabs
ok('ALL tab', (await page.getByRole('tab', { name: 'all timeframes combined' }).count()) === 1);
for (const t of tfs) ok(`tab ${t}`, (await page.getByRole('tab', { name: `${t} only` }).count()) === 1);
const allTotal = st.reduce((a, r) => a + r.total, 0);
ok('ALL shows the combined total', body.includes(mb(allTotal)) && body.includes('every timeframe combined'), mb(allTotal));

// switching to a timeframe changes both the total and the rows
for (const t of ['15m', '1d']) {
  // by role: the download section has pills with the same labels
  await page.getByRole('tab', { name: `${t} only` }).click();
  await page.waitForTimeout(1200);
  body = await page.evaluate(() => document.body.innerText);
  const tot = st.filter(r => r.tf === t).reduce((a, r) => a + r.total, 0);
  const coins = new Set(st.filter(r => r.tf === t).map(r => r.coin)).size;
  ok(`${t} tab totals only ${t}`, body.includes(mb(tot)), `${mb(tot)} vs ALL ${mb(allTotal)}`);
  ok(`${t} tab says "${t} only"`, body.includes(`${t} only`));
  ok(`${t} tab counts its own coins`, body.includes(`${coins} coins`), `${coins}`);
  // every timeframe chip on screen must be this tab's
  const chips = await page.evaluate(() => {
    const t2 = [...document.querySelectorAll('table')].find(t => t.textContent.includes('last updated'));
    return [...t2.querySelectorAll('tbody tr td:nth-child(2) span span')].map(s => s.textContent.trim());
  });
  ok(`${t} tab shows only ${t} rows`, chips.length > 0 && chips.every((c) => c === t), [...new Set(chips)].join(","));
}
ok('no js errors', errors.length === 0, errors[0] ?? '');
await page.screenshot({ path: '/tmp/storage-tabs.png', fullPage: false });
console.log(fails.length ? 'RESULT: FAIL ' + fails.join(', ') : 'RESULT: ALL PASS');
await b.close();
