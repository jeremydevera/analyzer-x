import { chromium } from "playwright";
const b = await chromium.launch();
const pg = await b.newPage({ viewport: { width: 1800, height: 1500 } });
const errs = []; pg.on("pageerror", e => errs.push(String(e)));
await pg.goto("http://localhost:8503", { waitUntil: "networkidle" });
await pg.waitForTimeout(10000);
const R = () => pg.locator('[data-testid="stHorizontalBlock"]').filter({ hasText: /1 YEAR/ });
for (let a = 0; a < 4; a++) {
  await pg.locator('[data-testid="stRadio"] label').filter({ hasText: /^Auto Trade$/ }).first().click({ force: true });
  await pg.waitForTimeout(9000);
  if (await R().count()) break;
}
const night = pg.locator('input[aria-label="Night mode"]');
const nightBox = pg.locator('label').filter({ hasText: /Night mode/i }).first();
const probe = async (tag) => {
  const v = await pg.evaluate(() => {
    const g=(el,...p)=>el?Object.fromEntries(p.map(k=>[k,getComputedStyle(el)[k]])):null;
    const sec=document.querySelector('[class*="st-key-tmsec_"]');
    const hdr=sec&&sec.querySelector('.tm-h');
    const k=hdr&&hdr.querySelector('.k');
    const th=document.querySelector('.tm-pt-h');
    const td=document.querySelector('.tm-pt:not(.tm-pt-h):not(.tm-pt-t)');
    return {
      sec:g(sec,"backgroundColor","borderTopWidth","borderTopColor","borderRadius","boxShadow","padding"),
      k:g(k,"fontFamily","fontSize","fontWeight","textTransform","color","letterSpacing"),
      th:g(th,"backgroundColor","fontSize","fontWeight","textTransform","padding","color"),
      td:g(td,"padding","fontSize","borderBottomColor"),
      app:getComputedStyle(document.querySelector('[data-testid="stAppViewContainer"]')).backgroundColor,
    };
  });
  console.log(`\n--- ${tag}`);
  console.log("  page   ", v.app);
  console.log("  card   ", v.sec.backgroundColor, "| radius", v.sec.borderRadius,
              "| border", v.sec.borderTopWidth, v.sec.borderTopColor, "| shadow", v.sec.boxShadow);
  console.log("  title  ", v.k.fontSize, v.k.fontWeight, v.k.textTransform,
              v.k.color, "|", v.k.fontFamily.split(",")[0]);
  console.log("  thead  ", v.th.backgroundColor, v.th.fontSize, v.th.fontWeight,
              v.th.textTransform, "pad", v.th.padding);
  console.log("  row    ", "pad", v.td.padding, v.td.fontSize, "sep", v.td.borderBottomColor);
};
await probe(await night.isChecked() ? "NIGHT" : "LIGHT");
await pg.screenshot({ path: `apexui-${await night.isChecked() ? "night" : "light"}.png` });
await nightBox.click({ force: true });
await pg.waitForTimeout(9000);
if (!(await R().count())) { for (let a=0;a<3;a++){ await pg.locator('[data-testid="stRadio"] label').filter({ hasText: /^Auto Trade$/ }).first().click({force:true}); await pg.waitForTimeout(8000); if (await R().count()) break; } }
await probe(await night.isChecked() ? "NIGHT" : "LIGHT");
await pg.screenshot({ path: `apexui-${await night.isChecked() ? "night" : "light"}.png` });
console.log("\nerrors:", errs.length, errs.slice(0,2).join(" | "));
await b.close();
