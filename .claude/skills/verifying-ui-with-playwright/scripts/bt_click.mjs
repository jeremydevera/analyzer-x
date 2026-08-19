import { chromium } from "playwright";
const b = await chromium.launch(); const p = await b.newPage({viewport:{width:1680,height:1200}});
await p.goto("http://localhost:8503", {waitUntil:"networkidle"}); await p.waitForTimeout(8000);
await p.locator('label', {hasText: "Auto Trade"}).first().click(); await p.waitForTimeout(5000);
await p.locator('[data-testid="stButton"] button').filter({hasText:/^Backtest ICT fair value gap/}).click();
await p.waitForTimeout(20000);
const body = await p.innerText("body");
for (const t of ["coin(s) tested","PROFIT TOTAL","WINS","LOSSES","BTC_USDT"])
  console.log(t, ":", body.includes(t) ? "shown" : "MISSING");
await p.screenshot({path:"auto-bt.png", fullPage:true});
await b.close();
