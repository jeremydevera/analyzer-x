import { chromium } from "playwright";
const b = await chromium.launch();
const pg = await b.newPage({ viewport: { width: 1800, height: 2200 } });
await pg.goto("http://localhost:8503", { waitUntil: "networkidle" });
await pg.waitForTimeout(11000);
for (let a=0;a<4;a++){
  await pg.locator('[data-testid="stRadio"] label').filter({ hasText: /^Auto Trade$/ }).first().click({force:true});
  await pg.waitForTimeout(9000);
  if (await pg.locator('.st-key-pos_real').count()) break;
}
const info = await pg.evaluate(() => {
  const box=document.querySelector('.st-key-pos_real');
  const btn=[...box.querySelectorAll('button')].find(b=>/close/i.test(b.innerText));
  if(!btn) return {noBtn:true, html: box.innerHTML.slice(0,300)};
  const chain=[]; let e=btn;
  for(let i=0;i<7 && e && e!==box;i++){
    const cs=getComputedStyle(e);
    chain.push({tag:e.tagName, tid:e.getAttribute('data-testid'), cls:(e.className||"").slice(0,60),
      h:Math.round(e.getBoundingClientRect().height), display:cs.display,
      align:cs.alignItems, minH:cs.minHeight, mt:cs.marginTop});
    e=e.parentElement;
  }
  const btns=[...box.querySelectorAll('button')].filter(b=>/close/i.test(b.innerText))
    .map(b=>({h:Math.round(b.getBoundingClientRect().height), top:Math.round(b.getBoundingClientRect().top)}));
  return {chain, btns};
});
console.log(JSON.stringify(info, null, 1));
await b.close();
