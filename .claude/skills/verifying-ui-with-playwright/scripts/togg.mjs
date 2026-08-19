import { chromium } from "playwright";
const b = await chromium.launch();
const pg = await b.newPage({ viewport: { width: 1800, height: 1200 } });
await pg.goto("http://localhost:8503", { waitUntil: "networkidle" });
await pg.waitForTimeout(9000);
for (const sel of ['[data-testid="stToggle"]', '[data-testid="stCheckbox"]', 'input[type="checkbox"]', '[role="switch"]']) {
  console.log(sel, "count:", await pg.locator(sel).count());
}
const t = await pg.locator('label').filter({ hasText: /Night mode/i });
console.log("Night mode labels:", await t.count());
if (await t.count()) console.log("html:", (await t.first().evaluate(n => n.outerHTML)).slice(0, 400));
await b.close();
