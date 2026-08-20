import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1600,height:1200});
await p.goto('http://localhost:8503', {waitUntil:'networkidle', timeout:120000});
await p.waitForTimeout(10000);
const r = await p.evaluate(() => {
  const walk=document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n; const out=[];
  while((n=walk.nextNode())){
    if (n.nodeValue?.trim()!=='backtest') continue;
    const el=n.parentElement; const rg=document.createRange(); rg.selectNodeContents(n);
    const chain=[]; let q=el;
    for(let i=0;i<4&&q;i++,q=q.parentElement)
      chain.push(q.tagName+'.'+(q.className||'').toString().slice(0,28)
                 +(q.getAttribute?.('data-testid')?'#'+q.getAttribute('data-testid'):''));
    out.push({lines:rg.getClientRects().length,
      w:+el.getBoundingClientRect().width.toFixed(1),
      size:getComputedStyle(el).fontSize, chain});
  }
  return out;
});
console.log(JSON.stringify(r,null,1));
await b.close();
