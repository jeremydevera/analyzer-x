import { chromium } from 'playwright-core';
const b = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' });
const p = await (await b.newContext({ viewport: { width: 1600, height: 1200 } })).newPage();
await p.goto('http://127.0.0.1:8503/trade', { waitUntil: 'domcontentloaded', timeout: 90000 });
await p.waitForTimeout(12000);
const got = await p.evaluate(() => {
  const t = [...document.querySelectorAll('table')].find(x => x.innerText.includes('DEMO W/L'));
  if (!t) return { err: 'no deployed table' };
  const head = [...t.querySelectorAll('thead th, thead td')].map(x => x.innerText.trim());
  const iD = head.indexOf('DEMO $'), iW = head.indexOf('DEMO W/L'), iT = head.indexOf('today $');
  const rows = [];
  for (const tr of t.querySelectorAll('tbody tr')) {
    const c = [...tr.children].map(x => x.innerText.trim().replace(/\n/g, ' '));
    rows.push({ id: c[0].split(' ')[0], today: c[iT], demo: c[iD], wl: c[iW] });
  }
  return { head, rows: rows.filter(r => r.demo !== '—').slice(0, 8), blank: rows.filter(r => r.demo === '—').length, total: rows.length };
});
console.log(JSON.stringify(got, null, 1));
await b.close();
