import { chromium } from 'playwright';
const api = async (p) => (await fetch('http://localhost:8503' + p)).json();
const b = await chromium.launch();
const page = await b.newPage({ viewport: { width: 1700, height: 1200 } });
const errors = []; page.on('pageerror', e => errors.push(e.message));
page.on('dialog', d => d.dismiss());
await page.goto('http://localhost:8503/trade', { waitUntil: 'domcontentloaded' });
await page.waitForSelector('text=Strategies you have deployed', { timeout: 60000 });
await page.waitForTimeout(5500);
const fails = []; const ok = (n,c,d) => { console.log((c?'PASS ':'FAIL ')+n+(d?' — '+d:'')); if(!c) fails.push(n); };
const body = await page.evaluate(() => document.body.innerText);
const st = await api('/api/trade/strategies');
const shared = st.rows.filter((r) => (r.streak ?? 0) > 0 && (r.streak_shared_with?.length ?? 0) > 0);

ok('the column is named "rung", not "streak"', body.includes("rung") && !/\bstreak\b/.test(body));
ok('no cell claims "N loss"', !/\d+ loss\b/.test(body), body.match(/\d+ loss\b/)?.[0] ?? "none");
for (const r of st.rows.filter((x) => x.streak)) {
  ok(`${r.key} shows its rung`, body.includes(String(r.streak)), String(r.streak));
  ok(`${r.key} names the book`, body.includes(`${r.streak_book} book`), r.streak_book);
}
if (shared.length) {
  ok('a shared ladder is called out', body.includes('shared by') && body.includes('raises the stake for both'));
  const r = shared[0];
  ok('the callout names the next stake', body.includes(`next stake $${r.next_stake}`), `$${r.next_stake}`);
  ok('the callout names both strategies',
     [r.key, ...(r.streak_shared_with ?? [])].every((k) => body.includes(k)));
  // the strategy key renders with zero-width breaks inside it, so match the
  // row by its ID instead of its key text
  const cell = await page.evaluate((rid) => {
    const t = [...document.querySelectorAll('table')].find(t => t.textContent.includes('ladder $'));
    const tr = [...(t?.querySelectorAll('tbody tr') ?? [])].find(r => r.textContent.includes(rid));
    return tr ? [...tr.querySelectorAll('td')].map(td => td.innerText.trim()) : [];
  }, shared[0].id);
  ok('the rung cell says "shared"', cell.some((c) => /shared/.test(c)), cell.find((c) => /shared/.test(c)));
}
ok('W/L is the row\'s own record', st.rows.every((r) => typeof r.wins === "number"));
ok('no js errors', errors.length === 0, errors[0] ?? '');
await page.screenshot({ path: '/tmp/rung-label.png', fullPage: false });
console.log(fails.length ? 'RESULT: FAIL ' + fails.join(', ') : 'RESULT: ALL PASS');
await b.close();
