import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1600,height:1200});
await p.goto('http://localhost:8503', {waitUntil:'networkidle', timeout:120000});
await p.waitForTimeout(10000);
await p.getByText('New Crypto',{exact:true}).first().click();
await p.waitForTimeout(7000);
const r = await p.evaluate(() => {
  const out=[];
  const walk=document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n;
  while((n=walk.nextNode())){
    const t=n.nodeValue?.trim();
    if(!['2026-08-19','+833.50%','VOLUME','$321.6k'].includes(t)) continue;
    const el=n.parentElement; const rg=document.createRange(); rg.selectNodeContents(n);
    const rects=[...rg.getClientRects()];
    const col=el.closest('[data-testid="stColumn"]');
    const cs=getComputedStyle(el);
    out.push({t, lines:rects.length,
      textW:+rects.reduce((a,r)=>a+r.width,0).toFixed(1),
      elW:+el.getBoundingClientRect().width.toFixed(1),
      colW:col?+col.getBoundingClientRect().width.toFixed(1):null,
      pad:cs.padding, font:cs.fontFamily.split(',')[0], size:cs.fontSize});
  }
  return out;
});
console.log(JSON.stringify(r,null,1));
await b.close();
