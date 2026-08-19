import { chromium } from "playwright";
const b = await chromium.launch(); const p = await b.newPage({viewport:{width:1680,height:1200}});
await p.goto("http://localhost:8503", {waitUntil:"networkidle"}); await p.waitForTimeout(9000);
await p.locator('label', {hasText: "Auto Trade"}).first().click(); await p.waitForTimeout(6000);
const n = await p.locator('[data-testid="stDataFrame"]').count();
console.log("dataframes on page:", n);
await p.screenshot({path:"pos-table.png", fullPage:false});
await b.close();
