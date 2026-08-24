import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1700,height:1000});
await p.goto('http://localhost:8503/trade', {waitUntil:'networkidle', timeout:120000});
await p.waitForTimeout(3500);
const n = await p.evaluate(() => {
  const t = [...document.querySelectorAll('table')];
  return t.map((x, i) => ({i, head: x.querySelector('tr')?.innerText.replace(/\s+/g,' ').slice(0,90)}));
});
console.log(JSON.stringify(n, null, 1));
const idx = n.findIndex(x => /books/i.test(x.head || ''));
if (idx >= 0) {
  const el = (await p.$$('table'))[idx];
  await el.scrollIntoViewIfNeeded(); await p.waitForTimeout(400);
  await el.screenshot({path:'grid_now.png'});
  console.log('shot table', idx);
} else console.log('no books table found');
await b.close();
