import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
const errs=[]; p.on('pageerror',e=>errs.push(String(e).slice(0,120)));
await p.setViewportSize({width:1500,height:1000});
await p.goto('http://localhost:8503/backtest', {waitUntil:'networkidle', timeout:120000});
await p.waitForTimeout(4500);
const r = await p.evaluate(() => {
  const panel = (t) => [...document.querySelectorAll('h3')]
    .find(h => h.innerText.trim() === t)?.closest('div');
  const bh = panel('Backtest history'), dh = panel('Deployment history');
  const box = e => e ? e.getBoundingClientRect() : null;
  const a = box(bh), c = box(dh);
  return {
    btHistoryTop: a ? Math.round(a.top + window.scrollY) : null,
    deployTop: c ? Math.round(c.top + window.scrollY) : null,
    btWidth: a ? Math.round(a.width) : null,
    deployWidth: c ? Math.round(c.width) : null,
    isBelow: a && c ? (a.top + window.scrollY) > (c.top + window.scrollY) : null,
    isTable: !!bh?.querySelector('table'),
    headers: bh ? [...bh.querySelectorAll('thead td, thead th')].map(x=>x.innerText.trim()) : [],
  };
});
console.log(JSON.stringify(r,null,1));
console.log('page errors:', errs);
await b.close();
