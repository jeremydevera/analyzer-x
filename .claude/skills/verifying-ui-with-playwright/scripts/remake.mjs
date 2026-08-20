import { chromium } from "playwright";
const b = await chromium.launch();
const pg = await b.newPage({ viewport: { width: 1800, height: 1500 } });
const errs = []; pg.on("pageerror", e => errs.push(String(e)));
await pg.goto("http://localhost:8503", { waitUntil: "networkidle" });
await pg.waitForTimeout(12000);
const side = pg.locator('[data-testid="stSidebar"]');
console.log("sidebar present:", await side.count());
if (await side.count()) {
  const txt = (await side.innerText()).replace(/\n+/g, " | ");
  console.log("rail:", txt.slice(0, 200));
}
// navigate via the rail
for (let a=0;a<3;a++){
  const btn = side.locator("button", { hasText: /^Auto Trade$/ }).first();
  if (await btn.count()) { await btn.click({force:true}); await pg.waitForTimeout(9000); }
  if (await pg.locator('.tm-pt-h').count()) break;
}
const v = await pg.evaluate(() => {
  const hdr = document.querySelector('.st-key-pos_real .tm-pt-h');
  const exp = document.querySelectorAll('.st-key-pos_real [data-testid="stExpander"]');
  const side = document.querySelector('[data-testid="stSidebar"]');
  return {
    posHeader: hdr && hdr.innerText.replace(/\n/g, " | "),
    cols: hdr ? getComputedStyle(hdr).gridTemplateColumns.split(" ").length : 0,
    expanders: exp.length,
    railW: side ? Math.round(side.getBoundingClientRect().width) : 0,
    mainW: Math.round(document.querySelector('[data-testid="stAppViewContainer"] .stMainBlockContainer, .stMainBlockContainer, [data-testid="stMain"]')?.getBoundingClientRect().width || 0),
    pills: document.querySelectorAll('.st-key-nav_page').length,
  };
});
console.log(JSON.stringify(v, null, 1));
console.log("errors:", errs.length, errs.slice(0,2).join(" | "));
await pg.screenshot({ path: "remake-full.png", fullPage: false });
const box = pg.locator('.st-key-pos_real').first();
if (await box.count()) { await box.scrollIntoViewIfNeeded(); await pg.waitForTimeout(600);
  const bx = await box.boundingBox();
  await pg.screenshot({ path: "remake-pos.png", clip:{x:Math.max(0,bx.x-30),y:Math.max(0,bx.y-70),width:1500,height:360} }); }
await b.close();
