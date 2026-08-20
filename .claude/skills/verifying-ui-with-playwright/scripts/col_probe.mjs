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
  const blocks=[...box.querySelectorAll('[data-testid="stHorizontalBlock"]')];
  const blk=blocks.find(b=>b.querySelector('.tm-pt:not(.tm-pt-h):not(.tm-pt-t)') && b.querySelector('button'));
  if(!blk) return {none:true, blocks:blocks.length};
  const cols=[...blk.querySelectorAll(':scope > [data-testid="stColumn"]')];
  const row=blk.querySelector('.tm-pt');
  const btn=blk.querySelector('button');
  const r=e=>{const x=e.getBoundingClientRect();return{top:Math.round(x.top),h:Math.round(x.height),mid:Math.round(x.top+x.height/2)};};
  return {
    block:{...r(blk), align:getComputedStyle(blk).alignItems},
    cols:cols.map(c=>({...r(c), display:getComputedStyle(c).display,
      align:getComputedStyle(c).alignItems, minH:getComputedStyle(c).minHeight})),
    row:r(row), rowWrap:r(row.parentElement), btn:r(btn),
    rowPad:getComputedStyle(row).padding, rowMinH:getComputedStyle(row).minHeight,
  };
});
console.log(JSON.stringify(out, null, 1));
await b.close();
