import { chromium } from "playwright";
const b = await chromium.launch();
const pg = await b.newPage({ viewport: { width: 1800, height: 1200 } });
await pg.goto("http://localhost:8503", { waitUntil: "networkidle" });
await pg.waitForTimeout(10000);
for (const sel of ['[data-testid="stRadio"] label', 'a[href]', '[role="tab"]', '[data-testid="stTabs"] button']) {
  const t = await pg.locator(sel).allInnerTexts().catch(()=>[]);
  console.log(sel, "->", JSON.stringify(t.slice(0,12)));
}
await b.close();
