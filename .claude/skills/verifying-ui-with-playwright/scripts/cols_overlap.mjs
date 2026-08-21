import { chromium } from 'playwright';
const b = await chromium.launch();
const fails = []; const ok = (n,c,d) => { console.log((c?'PASS ':'FAIL ')+n+(d?' — '+d:'')); if(!c) fails.push(n); };
for (const w of [1280, 1512, 1920]) {
  const page = await b.newPage({ viewport: { width: w, height: 1100 } });
  page.on('dialog', d => d.dismiss());
  await page.goto('http://localhost:8503/trade', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('text=Strategies you have deployed', { timeout: 60000 });
  await page.waitForTimeout(5000);
  // no cell's content may cross into the next column
  const bad = await page.evaluate(() => {
    const out = [];
    const tables = [...document.querySelectorAll('table')];
    if (!tables.length) return [{ why: 'no tables' }];
    tables.forEach((t, ti) => {
    t.querySelectorAll('tbody tr').forEach((tr) => {
      const tds = [...tr.querySelectorAll('td')];
      tds.forEach((td, i) => {
        const cell = td.getBoundingClientRect();
        [...td.querySelectorAll('*')].forEach((el) => {
          const r = el.getBoundingClientRect();
          if (r.width && r.right > cell.right + 1)
            out.push({ table: ti, col: i, over: Math.round(r.right - cell.right),
                       txt: (el.textContent || '').trim().slice(0, 14) });
        });
      });
    });
    });
    return out.slice(0, 6);
  });
  ok(`no cell overflows its column @${w}`, bad.length === 0, JSON.stringify(bad));
  const headers = await page.evaluate(() => {
    const t = [...document.querySelectorAll('table')].find(t => t.textContent.includes('ladder $'));
    return [...t.querySelectorAll('thead th')].map(th => ({
      h: th.textContent.trim().slice(0, 10), w: Math.round(th.getBoundingClientRect().width) }));
  });
  const books = headers.find(h => h.h === 'books');
  ok(`books column has room @${w}`, books && books.w >= 100, `${books?.w}px`);
  await page.close();
}
console.log(fails.length ? 'RESULT: FAIL ' + fails.join(', ') : 'RESULT: ALL PASS');
await b.close();
