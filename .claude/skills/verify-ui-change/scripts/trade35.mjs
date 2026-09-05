import { chromium } from 'playwright-core';
const b = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' });
const p = await (await b.newContext({ viewport: { width: 1500, height: 1300 } })).newPage();
p.on('pageerror', e => console.log('PAGEERROR', String(e).slice(0, 160)));
await p.goto('http://127.0.0.1:8503/trade', { waitUntil: 'domcontentloaded', timeout: 90000 });
await p.waitForTimeout(11000);
console.log('headings:', JSON.stringify(await p.evaluate(
  () => [...document.querySelectorAll('h1,h2,h3,h4')].map(x => x.innerText.trim()).slice(0, 14))));
const ids = await p.evaluate(() => [...document.querySelectorAll('table tbody tr')]
  .map(tr => [...tr.children].slice(0, 4).map(td => td.innerText.trim().replace(/\n/g, ' ')).join(' | '))
  .slice(0, 8));
console.log('first table rows:'); ids.forEach(r => console.log('  ', r));
const txt = await p.evaluate(() => document.body.innerText);
for (const s of ['GPNSTOCK', 'CGXLRJML', 'keltner', 'STRATEGIES', 'Strategies']) {
  console.log(`"${s}" on the page:`, txt.includes(s));
}
await p.screenshot({ path: 'trade35.png', fullPage: false });
await b.close();
