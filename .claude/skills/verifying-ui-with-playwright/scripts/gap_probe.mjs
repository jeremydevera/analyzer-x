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
const out = await pg.evaluate(() => {
  const box=document.querySelector('.st-key-pos_real');
  const blk=[...box.querySelectorAll('[data-testid="stHorizontalBlock"]')]
    .find(b=>b.querySelector('.tm-pt:not(.tm-pt-h):not(.tm-pt-t)') && b.querySelector('button'));
  const row=blk.querySelector('.tm-pt');
  const res=[]; let e=row;
  while(e && e!==blk){
    const cs=getComputedStyle(e), r=e.getBoundingClientRect();
    res.push({tag:e.tagName, tid:e.getAttribute('data-testid'),
      cls:(e.className||"").toString().slice(0,42),
      top:Math.round(r.top), h:Math.round(r.height),
      mt:cs.marginTop, mb:cs.marginBottom, pt:cs.paddingTop, gap:cs.gap,
      display:cs.display});
    e=e.parentElement;
  }
  const cs=getComputedStyle(blk), r=blk.getBoundingClientRect();
  res.push({tag:"BLOCK", top:Math.round(r.top), h:Math.round(r.height),
            gap:cs.gap, align:cs.alignItems, pt:cs.paddingTop});
  return res;
});
for (const x of out) console.log(JSON.stringify(x));
await b.close();
