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
  .evaluateAll(ns => ns.map((x, j) => `${j ? "DEMO" : "LIVE"}:${x.checked ? "on" : "off"}${x.disabled ? "/LOCKED" : ""}`))).join(" ");
const settle = async (i, want) => {
  for (let t = 0; t < 70; t++) {
    const s = await state(i);
    if (s.includes("LOCKED") === want) return s;
    await pg.waitForTimeout(1000);
  }
  return "TIMEOUT " + await state(i);
};
console.log("start        row0:", await state(0), "| row1:", await state(1));
console.log("row0 text   :", (await R().nth(0).innerText()).replace(/\n+/g, " | ").slice(0, 110));
console.log("row1 text   :", (await R().nth(1).innerText()).replace(/\n+/g, " | ").slice(0, 110));

// tick DEMO on the 4h row — PI papered on 30m AND 4h at once (nothing saved)
await R().nth(1).locator('[data-testid="stCheckbox"]').nth(1).click({ force: true });
await pg.waitForTimeout(12000);
console.log("both DEMO    row0:", await state(0), "| row1:", await state(1));
console.log("header      :", await pg.locator("text=/loaded/i").first().innerText());

// now go LIVE on the 30m row — the 4h row's LIVE must lock, its DEMO must not
await R().nth(0).locator('[data-testid="stCheckbox"]').nth(0).click({ force: true });
console.log("30m LIVE ->  row1:", await settle(1, true), "| row0:", await state(0));
console.log("header      :", await pg.locator("text=/loaded/i").first().innerText());
let bx = await R().first().boundingBox();
await pg.screenshot({ path: "livelock.png", clip: { x: 0, y: Math.max(0, bx.y - 175), width: 1900, height: 600 } });

// put everything back: LIVE off, 4h DEMO off
await R().nth(0).locator('[data-testid="stCheckbox"]').nth(0).click({ force: true });
console.log("30m LIVE off row1:", await settle(1, false), "| row0:", await state(0));
await R().nth(1).locator('[data-testid="stCheckbox"]').nth(1).click({ force: true });
await pg.waitForTimeout(12000);
console.log("restored     row0:", await state(0), "| row1:", await state(1));
console.log("errors      :", errs.length, errs.slice(0,2).join(" | "));
await b.close();
