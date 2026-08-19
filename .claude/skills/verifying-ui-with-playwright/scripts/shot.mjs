import { chromium } from "playwright";
const b = await chromium.launch();
const pg = await b.newPage({ viewport: { width: 1900, height: 1300 } });
const errs = []; pg.on("pageerror", e => errs.push(String(e)));
await pg.goto("http://localhost:8503", { waitUntil: "networkidle" });
await pg.waitForTimeout(9000);
const R = () => pg.locator('[data-testid="stHorizontalBlock"]').filter({ hasText: /1 YEAR/ });
for (let a = 0; a < 4; a++) {
  await pg.locator('[data-testid="stRadio"] label').filter({ hasText: /^Auto Trade$/ }).first().click({ force: true });
  await pg.waitForTimeout(9000);
  if (await R().count()) break;
}
const n = await R().count();
for (let i = 0; i < n; i++) {
  const boxes = await R().nth(i).locator('input[type="checkbox"]').evaluateAll(
    ns => ns.map((x, j) => `${j ? "DEMO" : "LIVE"}:${x.checked ? "on" : "off"}${x.disabled ? "/LOCKED" : ""}`));
  console.log(String(i).padStart(2), boxes.join(" ").padEnd(34),
    (await R().nth(i).innerText()).replace(/\n+/g, " | ").slice(0, 80));
}
console.log("header :", await pg.locator("text=/loaded/i").first().innerText());
console.log("errors :", errs.length);
const bx = await R().first().boundingBox();
await R().first().scrollIntoViewIfNeeded();
await pg.waitForTimeout(1200);
const bx2 = await R().first().boundingBox();
const top = Math.max(0, Math.min(bx2.y - 190, 1300 - 620));
await pg.screenshot({ path: "strategy-final.png", clip: { x: 0, y: top, width: 1900, height: 620 } });
await b.close();
