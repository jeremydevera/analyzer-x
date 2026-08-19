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
// wait for row `i` to reach a disabled-state, polling instead of sleeping:
// a rerun on this page takes longer than a fixed wait can safely assume.
const settle = async (i, want) => {
  for (let t = 0; t < 60; t++) {
    const s = await state(i);
    if (s.includes("LOCKED") === want) return s;
    await pg.waitForTimeout(1000);
  }
  return "TIMEOUT " + await state(i);
};
console.log("start    row0:", await state(0), "| row1:", await state(1));

await R().nth(0).locator('[data-testid="stCheckbox"]').nth(1).click({ force: true });
console.log("untick 30m  -> row1:", await settle(1, false), "| row0:", await state(0));

await R().nth(1).locator('[data-testid="stCheckbox"]').nth(1).click({ force: true });
console.log("arm 4h      -> row0:", await settle(0, true), "| row1:", await state(1));
console.log("header      :", await pg.locator("text=/loaded/i").first().innerText());
let bx = await R().first().boundingBox();
await pg.screenshot({ path: "lock-swapped.png", clip: { x: 0, y: Math.max(0, bx.y - 160), width: 1900, height: 560 } });

await R().nth(1).locator('[data-testid="stCheckbox"]').nth(1).click({ force: true });
console.log("untick 4h   -> row0:", await settle(0, false), "| row1:", await state(1));
await R().nth(0).locator('[data-testid="stCheckbox"]').nth(1).click({ force: true });
console.log("re-arm 30m  -> row1:", await settle(1, true), "| row0:", await state(0));
console.log("header      :", await pg.locator("text=/loaded/i").first().innerText());
console.log("errors      :", errs.length, errs.slice(0,2).join(" | "));
bx = await R().first().boundingBox();
await pg.screenshot({ path: "lock.png", clip: { x: 0, y: Math.max(0, bx.y - 170), width: 1900, height: 600 } });
await b.close();
