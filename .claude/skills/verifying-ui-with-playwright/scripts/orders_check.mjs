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
  const av=document.querySelector('.ap-av');
  const sub=document.querySelector('.ap-sub');
  const pills=[...document.querySelectorAll('.ap-pill')].slice(0,4)
    .map(e=>({t:e.innerText, ...g(e,"backgroundColor","color","borderRadius","padding","fontSize","fontWeight")}));
  const row=document.querySelector('.st-key-pos_real .tm-pt:not(.tm-pt-h):not(.tm-pt-t)');
  const hdr=document.querySelector('.st-key-pos_real .tm-pt-h');
  return {
    avatar:av&&{t:av.innerText,...g(av,"width","height","borderRadius","backgroundColor","color","fontSize","fontWeight")},
    sub:sub&&{t:sub.innerText,...g(sub,"fontSize","color")},
    pills, row:g(row,"minHeight","padding"), hdrText:hdr&&hdr.innerText.replace(/\n/g," | "),
  };
});
console.log("avatar :", JSON.stringify(v.avatar));
console.log("subline:", JSON.stringify(v.sub));
for (const p of v.pills) console.log("pill   :", JSON.stringify(p));
console.log("row    :", JSON.stringify(v.row));
console.log("header :", v.hdrText);
console.log("errors :", errs.length, errs.slice(0,2).join(" | "));
const box = pg.locator('.st-key-pos_real').first();
await box.scrollIntoViewIfNeeded(); await pg.waitForTimeout(700);
const bx = await box.boundingBox();
await pg.screenshot({ path: "orders-mine.png", clip: { x: 150, y: Math.max(0,bx.y-70), width: 1620, height: 520 } });
await b.close();
