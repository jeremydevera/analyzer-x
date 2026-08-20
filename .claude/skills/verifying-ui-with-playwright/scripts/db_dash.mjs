import { chromium } from "playwright";
const b = await chromium.launch(); const p = await b.newPage({viewport:{width:1680,height:1400}});
await p.goto("http://localhost:8503", {waitUntil:"networkidle", timeout: 60000}); await p.waitForTimeout(10000);
await p.getByText("Backtest 2", {exact: true}).first().click(); await p.waitForTimeout(45000);
const body = await p.innerText("body");
for (const t of ["STORAGE USED", "% used", "Plan limit", "candles"])
  console.log(t, ":", new RegExp(t.replace(/[%]/g,"\\$&"), "i").test(body) ? "shown" : "MISSING");
const m = body.match(/([\d.]+)% used — ([\d.,]+) MB of ([\d,]+) MB/);
console.log("bar text:", m ? m[0] : "NOT FOUND");
await p.screenshot({path:"db-dash.png", fullPage:true});
await b.close();
