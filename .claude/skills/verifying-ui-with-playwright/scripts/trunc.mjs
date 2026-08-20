import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1600,height:1100});
await p.goto('http://localhost:8503', {waitUntil:'domcontentloaded', timeout:120000});
await p.waitForFunction(()=>document.querySelectorAll('.ani').length>0,{timeout:120000});
await p.waitForTimeout(3000);
const r = await p.evaluate(() => {
  // clipped text: scrollWidth exceeds clientWidth on a leaf
  const clipped = [];
  for (const el of document.querySelectorAll('div,span,p,b,label')) {
    if (el.children.length || el.offsetParent===null) continue;
    // .ani-sr is DELIBERATELY 1x1 with hidden overflow — it is the
    // accessible copy, not a clipped label. Counting it as clipped
    // reported 26 failures that were all working as designed.
    if (el.classList.contains('ani-sr')) continue;
    const t=(el.innerText||'').trim(); if(!t) continue;
    if (el.scrollWidth > el.clientWidth + 1)
      clipped.push({t: t.slice(0,20), by: el.scrollWidth-el.clientWidth});
  }
  const h2 = [...document.querySelectorAll('h2.tm-h')].map(h=>({
    display: getComputedStyle(h).display,
    k: h.querySelector('.k')?.getBoundingClientRect().right,
    v: h.querySelector('.v')?.getBoundingClientRect().left,
  }));
  const main = document.querySelector('.stMain');
  return {clipped: clipped.slice(0,10), clippedN: clipped.length,
          h2, pageHScroll: main.scrollWidth > main.clientWidth+1};
});
console.log('h2 spacer working:', JSON.stringify(r.h2.map(x=>({d:x.display, gap: x.v&&x.k?Math.round(x.v-x.k):null}))));
console.log('clipped leaves:', r.clippedN, JSON.stringify(r.clipped));
console.log('page scrolls sideways:', r.pageHScroll);
await b.close();
