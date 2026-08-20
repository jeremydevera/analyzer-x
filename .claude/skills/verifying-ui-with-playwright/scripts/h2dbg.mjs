import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1600,height:1100});
await p.goto('http://localhost:8503', {waitUntil:'domcontentloaded', timeout:120000});
await p.waitForFunction(()=>document.querySelectorAll('h2.tm-h').length>0,{timeout:120000});
await p.waitForTimeout(2000);
const r = await p.evaluate(() => {
  const h = document.querySelector('h2.tm-h');
  const k = h.querySelector('.k'), rr = h.querySelector('.r'), v = h.querySelector('.v');
  const box = e => { const b=e.getBoundingClientRect();
    return {w:Math.round(b.width), l:Math.round(b.left), r:Math.round(b.right)}; };
  const cs = getComputedStyle(h), cr = rr?getComputedStyle(rr):null;
  return {h2: {...box(h), display:cs.display, gap:cs.gap, width:cs.width},
          k: k?box(k):null,
          r: rr?{...box(rr), flex:cr.flex, flexGrow:cr.flexGrow, display:cr.display, w:cr.width}:'MISSING .r',
          v: v?box(v):null,
          parentDisplay: getComputedStyle(h.parentElement).display,
          parentW: Math.round(h.parentElement.getBoundingClientRect().width)};
});
console.log(JSON.stringify(r,null,1));
await b.close();
