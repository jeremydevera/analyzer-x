import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1600,height:1100});
await p.goto('http://localhost:8503', {waitUntil:'domcontentloaded', timeout:120000});
await p.waitForFunction(()=>document.querySelectorAll('.mv').length>0,{timeout:120000});
await p.waitForTimeout(2500);
const r = await p.evaluate(() => {
  const want = ['Forget saved keys','MEXC API KEYS','Save keys','ALICE, APEX, PI, PROVE','4 STRATEGIES'];
  const out = [];
  for (const el of document.querySelectorAll('*')) {
    if (el.children.length || el.offsetParent===null) continue;
    const t = (el.innerText||'').trim();
    if (!want.includes(t)) continue;
    const chain=[]; let n=el;
    for (let i=0;i<4&&n;i++,n=n.parentElement){
      const cs=getComputedStyle(n);
      chain.push({tag:n.tagName, testid:n.getAttribute?.('data-testid'),
        cls:(n.className||'').toString().slice(0,32),
        color:cs.color, bg:cs.backgroundColor});
    }
    out.push({t, chain});
  }
  return out;
});
for (const x of r) { console.log('##', x.t);
  for (const c of x.chain) console.log('   ', c.tag, c.testid||'', c.cls, '| color', c.color, '| bg', c.bg); }
await b.close();
