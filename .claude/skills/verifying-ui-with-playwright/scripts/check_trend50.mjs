import { chromium } from "playwright";
const b = await chromium.launch();
const pg = await b.newPage({ viewport: { width: 1680, height: 1050 } });
await pg.goto("http://localhost:8503", { waitUntil: "networkidle" });
await pg.waitForTimeout(8000);
await pg.getByText("Trade", { exact: true }).first().click();
await pg.waitForTimeout(6000);
// tick the Hour4 lane
const hour4 = pg.locator('[data-testid="stCheckbox"]').filter({ hasText: /^Hour4/ });
await hour4.locator("label").first().click();
await pg.waitForTimeout(6000);
// open the Hour4 lane's strategy selectbox (the newest one containing HOUR4 header nearby)
const boxes = pg.locator('[data-testid="stSelectbox"]');
const n = await boxes.count();
let opened = false;
for (let i = 0; i < n; i++) {
  const box = boxes.nth(i);
  const ctx = await box.locator("xpath=ancestor::div[contains(@class,'stColumn')][1]").innerText().catch(() => "");
  if (/HOUR4/i.test(ctx)) {
    await box.click();
    opened = true;
    break;
  }
}
if (!opened) { await boxes.last().click(); }
await pg.waitForTimeout(1500);
const opts = await pg.locator('[data-baseweb="popover"] li').allInnerTexts();
console.log("OPTIONS:", JSON.stringify(opts));
const hit = opts.find(o => /Trend 50/i.test(o));
console.log(hit ? "TREND50-PRESENT: " + hit : "TREND50-MISSING");
await pg.screenshot({ path: "trend50-picker.png", fullPage: false });
await b.close();
