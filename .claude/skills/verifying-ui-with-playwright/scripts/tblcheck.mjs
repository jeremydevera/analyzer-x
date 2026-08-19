import { chromium } from "playwright";
const b = await chromium.launch();
const pg = await b.newPage({ viewport: { width: 1800, height: 1400 } });
const errs = []; pg.on("pageerror", e => errs.push(String(e)));
await pg.goto("http://localhost:8503", { waitUntil: "networkidle" });
await pg.waitForTimeout(11000);
const R = () => pg.locator('[data-testid="stHorizontalBlock"]').filter({ hasText: /1 YEAR/ });
for (let a=0;a<4;a++){
  await pg.locator('[data-testid="stRadio"] label').filter({ hasText: /^Auto Trade$/ }).first().click({force:true});
  await pg.waitForTimeout(9000);
  if (await R().count()) break;
}
const v = await pg.evaluate(() => {
  const g=(el,...p)=>el?Object.fromEntries(p.map(k=>[k,getComputedStyle(el)[k]])):null;
  const h=document.querySelector('.tm-pt-h');
  const r=document.querySelector('.tm-pt:not(.tm-pt-h):not(.tm-pt-t)');
  const root=getComputedStyle(document.documentElement);
  return {
    header:g(h,"textTransform","fontSize","fontWeight","letterSpacing","padding","backgroundColor","whiteSpace"),
    row:g(r,"padding","minHeight","fontSize","borderBottomColor"),
    tok:{accent:root.getPropertyValue('--accent').trim(), r:root.getPropertyValue('--r').trim()},
  };
});
console.log("grid header:", JSON.stringify(v.header));
console.log("grid row   :", JSON.stringify(v.row));
console.log("tokens     :", JSON.stringify(v.tok));
console.log("errors     :", errs.length);
const hdr = pg.locator('.tm-pt-h').first();
await hdr.scrollIntoViewIfNeeded(); await pg.waitForTimeout(600);
const bx = await hdr.boundingBox();
await pg.screenshot({ path: "tbl-apex-light.png", clip: { x: 150, y: Math.max(0,bx.y-120), width: 1600, height: 470 } });
await b.close();
