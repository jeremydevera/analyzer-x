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
const state = async (i) => (await R().nth(i).locator('input[type="checkbox"]')
  .evaluateAll(ns => ns.map(x => `${x.checked ? "ON" : "off"}${x.disabled ? "/LOCKED" : ""}`))).join(" ");
console.log("before  · row0 trend50 30m PI:", await state(0));
console.log("before  · row1 mom15  4h PI:", await state(1));

// untick trend50's DEMO — PI is released, the 4h row must become armable
await R().nth(0).locator('[data-testid="stCheckbox"]').nth(1).click({ force: true });
await pg.waitForTimeout(7000);
console.log("released· row0 trend50 30m PI:", await state(0));
console.log("released· row1 mom15  4h PI:", await state(1));

// now arm the 4h row instead — the 30m row must lock
await R().nth(1).locator('[data-testid="stCheckbox"]').nth(1).click({ force: true });
await pg.waitForTimeout(7000);
console.log("swapped · row0 trend50 30m PI:", await state(0));
console.log("swapped · row1 mom15  4h PI:", await state(1));
console.log("header  :", await pg.locator("text=/loaded/i").first().innerText());
const box = await R().first().boundingBox();
await pg.screenshot({ path: "lock-swapped.png", clip: { x: 0, y: Math.max(0, box.y - 150), width: 1900, height: 560 } });

// put it back the way the operator has it
await R().nth(1).locator('[data-testid="stCheckbox"]').nth(1).click({ force: true });
await pg.waitForTimeout(7000);
await R().nth(0).locator('[data-testid="stCheckbox"]').nth(1).click({ force: true });
await pg.waitForTimeout(7000);
console.log("restored· row0 trend50 30m PI:", await state(0));
console.log("restored· row1 mom15  4h PI:", await state(1));
console.log("errors  :", errs.length, errs.slice(0,2).join(" | "));
const b2 = await R().first().boundingBox();
await pg.screenshot({ path: "lock.png", clip: { x: 0, y: Math.max(0, b2.y - 170), width: 1900, height: 600 } });
await b.close();
