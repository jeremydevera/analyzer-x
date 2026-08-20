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
const ss = await api('/api/analysis/social/sources');

ok('social control present (Sentiment picked by default)', body.includes('where the Sentiment Analyst reads posts'));
ok('default is the free source', body.includes('free, keyless'));
ok('X keyword box hidden while StockTwits selected', !body.includes('extra X search terms'));

// pick X and check the metered note + keyword box appear
const sel = page.locator('select').filter({ hasText: 'StockTwits only' }).first();
await sel.selectOption('both');
await page.waitForTimeout(800);
body = await page.evaluate(() => document.body.innerText);
ok('metered warning appears for X', body.includes('spends credits'));
ok('X keyword box appears', body.includes('extra X search terms'));
ok('missing-key warning matches reality',
   ss.x_key_present ? !body.includes('is not set') : body.includes(`${ss.x_key_env} is not set`),
   `key present=${ss.x_key_present}`);

// deselecting the Sentiment analyst hides the whole block — no dead control
await page.locator('button', { hasText: /^Sentiment$/ }).first().click();
await page.waitForTimeout(600);
body = await page.evaluate(() => document.body.innerText);
ok('control hidden when Sentiment is off', !body.includes('where the Sentiment Analyst reads posts'));

// the finished X run shows what it actually used
await page.locator('button', { hasText: RID }).first().click();
await page.waitForTimeout(3500);
body = await page.evaluate(() => document.body.innerText);
const r = await api(`/api/analysis/${RID}`);
ok('run badge names its social source', body.includes(`social: ${r.spec.social_source}`), r.spec.social_source);
ok('run badge counts the X terms', body.includes(`+${r.spec.twitter_keywords.length} X terms`));
const rep = r.reports['Sentiment Analyst'] ?? '';
ok('report has an X/Twitter section', /x\/twitter/i.test(rep));
await page.locator('button', { hasText: 'Sentiment Analyst' }).first().click();
await page.waitForTimeout(800);
body = await page.evaluate(() => document.body.innerText);
ok('X findings visible on screen', body.includes('Robotaxi') || body.includes('X/Twitter'));
ok('no js errors', errors.length === 0, errors[0] ?? '');
await page.screenshot({ path: '/tmp/social-ui.png', fullPage: false });
console.log(fails.length ? 'RESULT: FAIL ' + fails.join(', ') : 'RESULT: ALL PASS');
await b.close();
