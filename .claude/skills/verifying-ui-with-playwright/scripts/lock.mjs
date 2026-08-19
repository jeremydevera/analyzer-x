import { chromium } from "playwright";
const b = await chromium.launch();
const pg = await b.newPage({ viewport: { width: 1900, height: 1300 } });
const errs = []; pg.on("pageerror", e => errs.push(String(e)));
await pg.goto("http://localhost:8503", { waitUntil: "networkidle" });
await pg.waitForTimeout(9000);
for (let a = 0; a < 4; a++) {
  await pg.locator('[data-testid="stRadio"] label').filter({ hasText: /^Auto Trade$/ }).first().click({ force: true });
  await pg.waitForTimeout(9000);
  if (await pg.locator('[data-testid="stHorizontalBlock"]').filter({ hasText: /1 YEAR/ }).count()) break;
  console.log("retry nav", a);
}

const rows = pg.locator('[data-testid="stHorizontalBlock"]').filter({ hasText: /1 YEAR/ });
const n = await rows.count();
console.log("strategy rows:", n);
for (let i = 0; i < n; i++) {
  const r = rows.nth(i);
  const t = (await r.innerText()).replace(/\n+/g, " | ");
  const boxes = await r.locator('input[type="checkbox"]').evaluateAll(
    ns => ns.map(x => `${x.checked ? "ON " : "off"}${x.disabled ? "/LOCKED" : ""}`));
  console.log(String(i).padStart(2), JSON.stringify(boxes).padEnd(30), t.slice(0, 90));
}
const head = await pg.locator("text=/loaded/i").first().innerText();
console.log("header :", head);
console.log("inputs :", JSON.stringify(await pg.locator('[data-testid="stTextInput"] input')
  .evaluateAll(ns => ns.map(x => x.getAttribute("aria-label")))));
console.log("errors :", errs.length, errs.slice(0,2).join(" | "));
const first = rows.first();
await first.scrollIntoViewIfNeeded();
await pg.waitForTimeout(600);
const box = await first.boundingBox();
await pg.screenshot({ path: "lock.png",
  clip: { x: 0, y: Math.max(0, box.y - 150), width: 1900, height: 620 } });
await b.close();
