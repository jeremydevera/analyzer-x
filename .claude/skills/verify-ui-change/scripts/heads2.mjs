import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1600,height:1050});
for (const pg of ['?p=stocks','?p=llm-models']) {
  await p.goto('http://localhost:8503/'+pg, {waitUntil:'domcontentloaded', timeout:120000});
  await p.waitForFunction(()=>document.querySelector('h1')!==null,{timeout:120000});
  await p.waitForTimeout(3500);
  const r = await p.evaluate(() => [...document.querySelectorAll('h1,h2,h3,h4,h5')]
    .filter(h=>h.offsetParent)
    .map(h=>({lvl:h.tagName, t:h.innerText.trim().slice(0,34),
              cls:(h.className||'').toString().slice(0,24)})));
  console.log(pg, JSON.stringify(r));
}
await b.close();
