import { chromium } from 'playwright';
const api = async (p) => (await fetch('http://localhost:8503' + p)).json();
const b = await chromium.launch();
const page = await b.newPage({ viewport: { width: 1512, height: 1100 } });
page.on('dialog', d => d.dismiss());
const fails = []; const ok = (n,c,d) => { console.log((c?'PASS ':'FAIL ')+n+(d?' — '+d:'')); if(!c) fails.push(n); };
const j = await api('/api/jobs/btupdate');
console.log(`   (stopped=${j.stopped}, done ${j.done}/${j.total}, ${Math.round((Date.now()/1000-j.finished)/60)} min ago)`);
await page.goto('http://localhost:8503/backtest', { waitUntil: 'domcontentloaded' });
await page.waitForSelector('text=UPDATE BACKTEST', { timeout: 60000 });
await page.waitForTimeout(4500);
let body = await page.evaluate(() => document.body.innerText);
ok('the stopped job says STOPPED', /stopped/i.test(body) && body.includes('stopped by you'));
ok('it does NOT say finished', !/\bfinished Aug/i.test(body));
const amber = await page.evaluate(() =>
  [...document.querySelectorAll('div')].some(d => /rounded-full bg-warning-400/.test(d.className)));
const green = await page.evaluate(() =>
  [...document.querySelectorAll('div')].some(d => /rounded-full bg-success-500/.test(d.className)));
ok('the bar is amber', amber);
ok('the bar is NOT green', !green);
const width = await page.evaluate(() => {
  const el = [...document.querySelectorAll('div')].find(d => /rounded-full bg-warning-400/.test(d.className));
  return el ? el.style.width : null;
});
ok('the bar shows how far it got, not 100%', width && width !== '100%', `${width} for ${j.done}/${j.total}`);
ok('progress counted', body.includes(`${j.done}/${j.total}`), `${j.done}/${j.total}`);
const x = page.locator('button[aria-label="dismiss"]').first();
ok('dismiss present', await x.count() > 0);
await x.click(); await page.waitForTimeout(700);
body = await page.evaluate(() => document.body.innerText);
ok('dismiss clears it', !body.includes('stopped by you'));
console.log(fails.length ? 'RESULT: FAIL ' + fails.join(', ') : 'RESULT: ALL PASS');
await b.close();
