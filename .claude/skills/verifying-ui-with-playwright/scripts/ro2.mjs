import { chromium } from "playwright";
const b = await chromium.launch();
const pg = await b.newPage({ viewport: { width: 1900, height: 1300 } });
const errs = []; pg.on("pageerror", e => errs.push(String(e)));
await pg.goto("http://localhost:8503", { waitUntil: "networkidle" });
await pg.waitForTimeout(9000);
await pg.locator('[data-testid="stRadio"] label').filter({ hasText: /^Auto Trade$/ }).first().click();
await pg.waitForTimeout(10000);

const rows = pg.locator('[data-testid="stHorizontalBlock"]').filter({ hasText: /1 YEAR/ });
const n = await rows.count();
console.log("strategy rows:", n);
for (let i = 0; i < n; i++) {
  const t = (await rows.nth(i).innerText()).replace(/\n+/g, " | ");
  console.log(String(i).padStart(2), t.slice(0, 150));
}
const labels = await pg.locator('[data-testid="stTextInput"] input')
  .evaluateAll(ns => ns.map(n => n.getAttribute("aria-label") || n.placeholder || "?"));
console.log("text inputs:", JSON.stringify(labels));
console.log("exceptions :", errs.length);

const first = rows.first();
await first.scrollIntoViewIfNeeded();
await pg.waitForTimeout(800);
const box = await first.boundingBox();
await pg.screenshot({ path: "ro-contracts.png",
  clip: { x: 0, y: Math.max(0, box.y - 140), width: 1900, height: Math.min(700, 1300 - Math.max(0, box.y-140)) } });
await b.close();
