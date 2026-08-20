import { chromium } from 'playwright';
const BASE = 'http://localhost:8503';
const api = async (p) => (await fetch(BASE + p)).json();
const browser = await chromium.launch();
const fails = []; const ok = (n,c,d) => { console.log((c?'PASS ':'FAIL ')+n+(d?' — '+d:'')); if(!c) fails.push(n); };

// the API must answer through the UI's own origin — one port for the operator
const h = await api('/api/health');
ok('same-origin API proxy', h.ok === true, `candles ${h.storage.candles.files} files`);

const SCREENS = [
  ['/',            'Backtest',    ['Stored strategies']],
  ['/trade',       'Auto Trade',  ['Open positions', 'Strategies', 'Runner feed']],
  ['/backtest',    'Backtest',    ['Market data & backtests', 'Size per coin']],
  ['/new-crypto',  'New Crypto',  ['New on MEXC', 'Announced, not trading yet']],
  ['/models',      'LLM Models',  ['Model health', 'Add a model']],
  ['/analysis',    'Analysis',    ['Run an analysis', 'Recent runs']],
];

for (const [path, nav, needles] of SCREENS) {
  const page = await browser.newPage({ viewport: { width: 1680, height: 1200 } });
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  page.on('dialog', d => d.dismiss());
  const resp = await page.goto(BASE + path, { waitUntil: 'networkidle' });
  await page.waitForTimeout(4500);
  const body = await page.evaluate(() => document.body.innerText);
  ok(`${path} serves 200`, resp.status() === 200, String(resp.status()));
  for (const nd of needles) ok(`${path} shows "${nd}"`, body.includes(nd));
  ok(`${path} no js errors`, errors.length === 0, errors[0] ?? '');
  // no template chrome anywhere
  for (const gone of ['TailAdmin', 'Musharof', 'Upgrade To Pro'])
    ok(`${path} free of "${gone}"`, !body.includes(gone));
  // every screen can reach every other one
  const links = await page.evaluate(() => [...document.querySelectorAll('nav a')].map(a => a.getAttribute('href')));
  ok(`${path} nav has all 5 screens`,
     ['/trade','/backtest','/new-crypto','/analysis','/models'].every(p => links.includes(p)),
     links.join(','));
  await page.close();
}
console.log(fails.length ? `RESULT: FAIL (${fails.length}) ` + fails.join(', ') : 'RESULT: ALL PASS');
await browser.close();
