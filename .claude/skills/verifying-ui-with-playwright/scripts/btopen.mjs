import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1600,height:1200});
await p.goto('http://localhost:8503', {waitUntil:'networkidle', timeout:120000});
await p.waitForTimeout(10000);
await p.getByText('Back Test',{exact:true}).first().click();
await p.waitForTimeout(7000);
const r = await p.evaluate(() => {
  const leaf = [...document.querySelectorAll('*')].find(e =>
      /^open the report$/i.test(e.innerText?.trim()||'') && !e.children.length);
  if (!leaf) return 'not found';
  const chain=[]; let n=leaf;
  for(let i=0;i<5&&n;i++,n=n.parentElement){
    const s=getComputedStyle(n);
    chain.push({tag:n.tagName, cls:(n.className||'').toString().slice(0,34),
      testid:n.getAttribute?.('data-testid'), color:s.color, bg:s.backgroundColor});
  }
  return chain;
});
console.log(JSON.stringify(r,null,1));
await b.close();
