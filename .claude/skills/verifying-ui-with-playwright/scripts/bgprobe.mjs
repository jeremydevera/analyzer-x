import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1600,height:1200});
await p.goto('http://localhost:8503', {waitUntil:'networkidle', timeout:120000});
await p.waitForTimeout(10000);
const look = async (nav, re) => {
  if (nav) { await p.getByText(nav,{exact:true}).first().click(); await p.waitForTimeout(6500); }
  const r = await p.evaluate((src) => {
    const rx=new RegExp(src,'i');
    const el=[...document.querySelectorAll('*')].find(e=>rx.test(e.innerText?.trim()||'')
             && !e.children.length && e.offsetParent);
    if(!el) return 'not found';
    let n=el, hops=0;
    while(n){ const c=getComputedStyle(n).backgroundColor;
      if(c && c!=='rgba(0, 0, 0, 0)')
        return {text:getComputedStyle(el).color, bg:c, hops,
                bgTag:n.tagName, bgTestid:n.getAttribute?.('data-testid'),
                bgCls:(n.className||'').toString().slice(0,60)};
      n=n.parentElement; hops++; }
    return 'no bg';
  }, re);
  console.log('##', re, JSON.stringify(r));
};
await look(null, '^Auto Trade$');
await look('LLM Models', '^Add model$');
await look('New Crypto', '^Filters$');
await b.close();
