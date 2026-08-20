import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1600,height:1200});
await p.goto('http://localhost:8503', {waitUntil:'networkidle', timeout:120000});
await p.waitForTimeout(10000);
await p.getByText('Back Test', {exact:true}).first().click();
await p.waitForTimeout(7000);
const r = await p.evaluate(() => {
  const el = [...document.querySelectorAll('*')].find(e =>
      /^download$/i.test(e.innerText?.trim()||'') && !e.children.length);
  const chain = []; let n = el;
  for (let i=0;i<5 && n;i++,n=n.parentElement) {
    const s = getComputedStyle(n);
    chain.push({tag:n.tagName, cls:(n.className||'').toString().slice(0,50),
      testid:n.getAttribute?.('data-testid'), disabled:n.disabled,
      ariaDis:n.getAttribute?.('aria-disabled'),
      color:s.color, opacity:s.opacity, bg:s.backgroundColor});
  }
  return chain;
});
console.log(JSON.stringify(r,null,1));
await b.close();
