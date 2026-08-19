import { chromium } from "playwright";
const b = await chromium.launch();
const pg = await b.newPage({ viewport: { width: 1800, height: 1400 } });
const errs = []; pg.on("pageerror", e => errs.push(String(e)));
await pg.goto("http://localhost:8503", { waitUntil: "networkidle" });
await pg.waitForTimeout(10000);
const R = () => pg.locator('[data-testid="stHorizontalBlock"]').filter({ hasText: /1 YEAR/ });
for (let a = 0; a < 4; a++) {
  await pg.locator('[data-testid="stRadio"] label').filter({ hasText: /^Auto Trade$/ }).first().click({ force: true });
  await pg.waitForTimeout(9000);
  if (await R().count()) break;
}
const feed = pg.locator('.tm-feed').first();
await feed.scrollIntoViewIfNeeded();
await pg.waitForTimeout(800);
const lines = (await feed.innerText()).split("\n").filter(Boolean).slice(0, 8);
console.log("runner log lines as rendered:");
for (const l of lines) console.log("   " + l.slice(0, 96));
const old = lines.filter(l => /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}/.test(l)).length;
const nu  = lines.filter(l => /^[A-Z][a-z]{2} \d{1,2} \d{1,2}:\d{2}:\d{2}(AM|PM)/.test(l)).length;
console.log(`\n24-hour stamps left: ${old}   am/pm stamps: ${nu}`);
console.log("errors:", errs.length);
const bx = await feed.boundingBox();
await pg.screenshot({ path: "feed-ampm.png", clip: { x: Math.max(0,bx.x-20), y: Math.max(0,bx.y-40), width: Math.min(1700, bx.width+40), height: 340 } });
await b.close();
