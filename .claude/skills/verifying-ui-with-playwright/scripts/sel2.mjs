import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1600,height:1200});
await p.goto('http://localhost:8503', {waitUntil:'networkidle', timeout:120000});
await p.waitForTimeout(10000);
const look = async (label, re) => {
  const r = await p.evaluate((src) => {
    const rx = new RegExp(src, 'i');
    const el = [...document.querySelectorAll('*')].find(e =>
        rx.test(e.innerText?.trim()||'') && !e.children.length && e.offsetParent);
    if (!el) return 'not found';
    const chain=[]; let n=el;
    for (let i=0;i<4&&n;i++,n=n.parentElement){ const s=getComputedStyle(n);
      chain.push({tag:n.tagName, testid:n.getAttribute?.('data-testid'),
        cls:(n.className||'').toString().slice(0,40),
        color:s.color, bg:s.backgroundColor}); }
    return chain;
  }, re);
  console.log('##', label, JSON.stringify(r,null,1));
};
await look('nav active', '^Auto Trade$');
await p.getByText('LLM Models', {exact:true}).first().click();
await p.waitForTimeout(6000);
await look('Add model', '^Add model$');
await p.getByText('New Crypto', {exact:true}).first().click();
await p.waitForTimeout(6000);
await look('Filters', '^Filters$');
await b.close();
