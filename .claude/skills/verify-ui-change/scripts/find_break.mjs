import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1600,height:1050});
await p.goto('http://localhost:8503/?p=backtest-2', {waitUntil:'domcontentloaded', timeout:120000});
await p.waitForFunction(()=>document.querySelectorAll('[data-baseweb="select"]').length>0,{timeout:120000});
await p.waitForTimeout(4000);
const r = await p.evaluate(() => {
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n; const out = [];
  while ((n = walk.nextNode())) {
    const t = n.nodeValue?.trim();
    if (t !== '1000000BABYDOGE') continue;
    const el = n.parentElement; const cs = getComputedStyle(el);
    const rg = document.createRange(); rg.selectNodeContents(n);
    out.push({tag: el.tagName, cls: (el.className||'').toString().slice(0,40),
      role: el.getAttribute('role'), testid: el.getAttribute('data-testid'),
      ws: cs.whiteSpace, lines: rg.getClientRects().length,
      w: Math.round(el.getBoundingClientRect().width),
      visible: el.offsetParent !== null,
      parent: el.parentElement?.tagName + '.' +
              (el.parentElement?.className||'').toString().slice(0,34)});
  }
  return out;
});
console.log(JSON.stringify(r,null,1));
await b.close();
