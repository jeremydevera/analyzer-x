import { chromium } from "playwright";
const b = await chromium.launch();
const pg = await b.newPage({ viewport: { width: 1800, height: 1400 } });
const errs = []; pg.on("pageerror", e => errs.push(String(e)));
await pg.goto("http://localhost:8503", { waitUntil: "networkidle" });
await pg.waitForTimeout(9000);
const R = () => pg.locator('[data-testid="stHorizontalBlock"]').filter({ hasText: /1 YEAR/ });
for (let a = 0; a < 4; a++) {
  await pg.locator('[data-testid="stRadio"] label').filter({ hasText: /^Auto Trade$/ }).first().click({ force: true });
  await pg.waitForTimeout(9000);
  if (await R().count()) break;
}
const cap = pg.locator("text=/page \\d+ of \\d+/i").first();
await cap.scrollIntoViewIfNeeded();
await pg.waitForTimeout(800);
console.log("caption:", await cap.innerText());
// count the rows of the EVERY TRADE table on this page
const rows = await pg.evaluate(() => {
  const heads = [...document.querySelectorAll('div')].filter(d => /^EVERY TRADE$/i.test(d.textContent.trim()));
  if (!heads.length) return "header not found";
  let n = heads[heads.length-1].parentElement;
  for (let i = 0; i < 6 && n; i++, n = n.parentElement) {
    const r = n.querySelectorAll('.tm-pt');
    if (r.length > 2) return r.length;
  }
  return "rows not found";
});
console.log("tm-pt rows in EVERY TRADE (header + rows + total):", rows);
const btns = await pg.locator('[data-testid="stHorizontalBlock"] button').evaluateAll(
  ns => ns.map(n => n.innerText.trim()).filter(t => /^\d+$/.test(t)));
console.log("page number buttons:", JSON.stringify(btns));
const onPill = await pg.locator('.tm-pg-on').allInnerTexts();
console.log("current-page pill:", JSON.stringify(onPill));
const box = await cap.boundingBox();
await pg.screenshot({ path: "ui-pagination.png",
  clip: { x: 150, y: Math.max(0, box.y - 430), width: 1560, height: 500 } });
// click page 3 and confirm the slice moves
if (btns.includes("3")) {
  await pg.locator('[data-testid="stHorizontalBlock"] button').filter({ hasText: /^3$/ }).first().click({ force: true });
  await pg.waitForTimeout(6000);
  console.log("after clicking 3:", await pg.locator("text=/page \\d+ of \\d+/i").first().innerText());
  console.log("pill now:", JSON.stringify(await pg.locator('.tm-pg-on').allInnerTexts()));
}
console.log("errors:", errs.length);
await b.close();
