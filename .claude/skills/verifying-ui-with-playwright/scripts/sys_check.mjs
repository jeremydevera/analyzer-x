import { chromium } from "playwright";
const b = await chromium.launch();
const pg = await b.newPage({ viewport: { width: 1800, height: 1500 } });
const errs = []; pg.on("pageerror", e => errs.push(String(e)));
await pg.goto("http://localhost:8503", { waitUntil: "networkidle" });
await pg.waitForTimeout(11000);
for (let a=0;a<4;a++){
  await pg.locator('[data-testid="stRadio"] label').filter({ hasText: /^Auto Trade$/ }).first().click({force:true});
  await pg.waitForTimeout(9000);
  if (await pg.locator('.tm-rib').count()) break;
}
const out = await pg.evaluate(() => {
  const g=(el,...p)=>el?Object.fromEntries(p.map(k=>[k,getComputedStyle(el)[k]])):null;
  const tile=document.querySelector('.tm-rib > div');
  const r=tile.getBoundingClientRect();
  const tbl=document.querySelector('.tm-tbl');
  const posHdrCol=document.querySelector('.st-key-pos_real [data-testid="stHorizontalBlock"] [data-testid="stColumn"]');
  return {
    tile:{w:Math.round(r.width),h:Math.round(r.height),
      ...g(tile,"padding","gap","borderRadius","borderTopWidth","backgroundColor","display")},
    label:g(tile.querySelector('.l'),"fontSize","fontWeight","textTransform","color"),
    icon:g(tile.querySelector('.ic'),"width","height","borderRadius","backgroundColor","color"),
    value:g(tile.querySelector('.n'),"fontSize","fontWeight"),
    sub:g(tile.querySelector('.s'),"fontSize","color"),
    tblCard:g(tbl,"borderTopWidth","borderTopColor","borderRadius","overflow"),
    posBorder:g(posHdrCol,"borderTopWidth","borderLeftWidth"),
  };
});
console.log(JSON.stringify(out, null, 1));
console.log("errors:", errs.length);
const rib = pg.locator('.tm-rib').first();
await rib.scrollIntoViewIfNeeded(); await pg.waitForTimeout(700);
const bx = await rib.boundingBox();
await pg.screenshot({ path: "sys-apex.png", clip: { x: 150, y: Math.max(0,bx.y-70), width: 1640, height: 300 } });
await b.close();
