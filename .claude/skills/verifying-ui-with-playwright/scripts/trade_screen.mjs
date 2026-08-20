import { chromium } from 'playwright';
const api = async (p) => (await fetch('http://localhost:8787' + p)).json();
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1680, height: 1400 } });
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
page.on('dialog', (d) => d.dismiss());   // never confirm a real save/stop in a test

await page.goto('http://localhost:3000/trade', { waitUntil: 'networkidle' });
await page.waitForTimeout(5000);
const fails = [];
const ok = (n, c, d) => { console.log((c ? 'PASS ' : 'FAIL ') + n + (d ? ' — ' + d : '')); if (!c) fails.push(n); };
const body = await page.evaluate(() => document.body.innerText);
const s = await api('/api/trade/summary');
const st = await api('/api/trade/strategies');
const fm = (v) => `${v >= 0 ? '+' : ''}${v.toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2})}`;
const num = (t) => parseFloat(String(t).replace(/[+,$]/g, ''));

// --- structural: labels derived from data, counts exact (these never drift)
ok('mode badge matches API', body.includes(s.mode), `api mode=${s.mode}`);
ok('pid shown', s.pid ? body.includes(`pid ${s.pid}`) : true, `pid=${s.pid}`);
ok('today closed matches API', body.includes(fm(s.today_real.total)), `today=${fm(s.today_real.total)}`);
ok('today W/L label', body.includes(`${s.today_real.wins}W / ${s.today_real.losses}L`));
ok('positions caption counts', body.includes(`${s.open_positions.length} real (exchange-confirmed) · ${s.paper_positions.length} paper (simulated)`));
for (const p of s.open_positions)
  ok(`position row ${p.symbol} present`, body.includes(p.symbol.replace('_USDT','')));
ok('strategy count', body.includes(`${st.rows.length} configured`), `${st.rows.length}`);
ok('sizing named', body.includes(`sizing ${st.sizing}`));
const armed = st.rows.filter(r => r.books.includes('real'));
for (const r of armed) ok(`armed row ${r.key}`, body.includes(r.key));
ok('ARMED badge count', (body.match(/ARMED/g) || []).length === armed.length, `vs ${armed.length} real-armed`);
const bc = await api('/api/trade/pnl/by-coin');
const coins = Object.entries(bc.coins);
ok('by-coin total derived', body.includes(`${coins.length} coins · ${fm(coins.reduce((a,[,v])=>a+v.pnl,0))} total`));
ok('runner feed present', body.includes('Runner feed'));

// --- live figures: DOM-internal consistency + tolerance vs a fresh sample.
// Unrealized PnL moves every second; exact string equality against a later
// API read is a flaky test, not a real check. The invariant that matters is
// that the itemised rows on screen SUM to the total on screen.
const dom = await page.evaluate(() => {
  const tiles = [...document.querySelectorAll('p')];
  const grab = (label) => {
    const p = tiles.find(e => e.textContent.trim().toUpperCase() === label);
    return p ? p.nextElementSibling?.textContent?.trim() : null;
  };
  // the POSITIONS table only — the strategies grid also contains "REAL"
  const posTable = [...document.querySelectorAll('table')]
    .find(t => t.textContent.includes('unrealized'));
  const rows = [...(posTable?.querySelectorAll('tbody tr') ?? [])]
    .map(tr => [...tr.querySelectorAll('td')].map(td => td.textContent.trim()))
    .filter(cells => cells[0] === 'REAL');
  return { wallet: grab('FUTURES WALLET'), allTime: grab('REAL · ALL TIME'),
           openTile: grab('OPEN · UNREALIZED'), rows };
});
const rowSum = dom.rows.reduce((a, r) => a + num(r[5]), 0);
ok('itemised REAL rows sum to the OPEN tile', Math.abs(rowSum - num(dom.openTile)) < 0.02,
   `rows=${rowSum.toFixed(2)} tile=${dom.openTile}`);
ok('wallet within tolerance of a fresh API read', Math.abs(num(dom.wallet) - s.equity) < 2,
   `page=${dom.wallet} api=${s.equity}`);
ok('all-time within tolerance', Math.abs(num(dom.allTime) - s.all_time) < 2,
   `page=${dom.allTime} api=${fm(s.all_time)}`);
ok('no js errors', errors.length === 0, errors[0] ?? '');
await page.screenshot({ path: '/tmp/react-trade.png', fullPage: true });
console.log(fails.length ? 'RESULT: FAIL ' + fails.join(', ') : 'RESULT: ALL PASS');
await browser.close();
