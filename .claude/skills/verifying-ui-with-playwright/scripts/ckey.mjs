import { chromium } from "playwright";
const b = await chromium.launch();
const pg = await b.newPage({ viewport: { width: 1800, height: 1400 } });
const errs = []; pg.on("pageerror", e => errs.push(String(e)));
await pg.goto("http://localhost:8503", { waitUntil: "networkidle" });
await pg.waitForTimeout(11000);
const R = () => pg.locator('[data-testid="stHorizontalBlock"]').filter({ hasText: /1 YEAR/ });
for (let a = 0; a < 4; a++) {
  await pg.locator('[data-testid="stRadio"] label').filter({ hasText: /^Auto Trade$/ }).first().click({ force: true });
  await pg.waitForTimeout(9000);
  if (await R().count()) break;
}
// press the bare `c` and `ctrl+c` on the page body, then look for the dialog
for (const key of ["c", "Control+c", "r"]) {
  await pg.evaluate(() => document.body.focus());
  await pg.keyboard.press(key);
  await pg.waitForTimeout(1500);
  const dlg = await pg.locator('[role="dialog"], [data-testid="stModal"]').count();
  const txt = await pg.locator("body").innerText();
  console.log(`after ${key.padEnd(9)} dialogs=${dlg} clear-cache text present=${/clear cache/i.test(txt)}`);
}
const txt = await pg.locator("body").innerText();
const xaut = (txt.match(/XAUT/g) || []).length;
console.log("\nXAUT mentions on the page:", xaut);
const cap = pg.locator("text=/page \\d+ of \\d+/i").first();
if (await cap.count()) { await cap.scrollIntoViewIfNeeded(); await pg.waitForTimeout(700);
  console.log("history caption:", await cap.innerText());
  const bx = await cap.boundingBox();
  await pg.screenshot({ path: "ui-clean.png", clip: { x: 150, y: Math.max(0, bx.y - 430), width: 1560, height: 500 } });
} else { console.log("history caption: (single page, no pager)");
  await pg.screenshot({ path: "ui-clean.png", fullPage: false }); }
console.log("errors:", errs.length);
await b.close();
