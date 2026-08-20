import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1600,height:1050});
await p.goto('http://localhost:8503/?p=backtest-2', {waitUntil:'domcontentloaded', timeout:120000});
await p.waitForFunction(()=>document.querySelectorAll('[data-baseweb="select"]').length>0,{timeout:120000});
await p.waitForTimeout(3500);
await p.click('[data-baseweb="select"]');
await p.waitForTimeout(1000);
const r = await p.evaluate(() => {
  const pop = document.querySelector('[data-baseweb="popover"]');
  const el = [...pop.querySelectorAll('li,div,span')]
    .find(e => e.children.length === 0 && /^Select all$/.test(e.innerText?.trim()||''));
  if (!el) return 'not found';
  const chain = []; let n = el;
  for (let i=0;i<4&&n;i++,n=n.parentElement) {
    const cs = getComputedStyle(n);
    chain.push({tag:n.tagName, role:n.getAttribute('role'),
      ariaSel:n.getAttribute('aria-selected'),
      cls:String(n.className||'').slice(0,26),
      color:cs.color, bg:cs.backgroundColor});
  }
  return chain;
});
console.log(JSON.stringify(r,null,1));
await b.close();
