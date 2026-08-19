import { chromium } from "playwright";
const b = await chromium.launch(); const p = await b.newPage({viewport:{width:1680,height:1050}});
await p.goto("http://localhost:8503", {waitUntil:"networkidle"}); await p.waitForTimeout(8000);
await p.locator('label', {hasText: "Auto Trade"}).first().click(); await p.waitForTimeout(6000);
await p.locator('[data-testid="stButton"] button').filter({hasText:/^Test connect$/}).click();
await p.waitForTimeout(15000);
const body = await p.innerText("body");
for (const line of ["Credentials present","Read account balance","Permission to place orders","Rest a stop","Futures wallet","Connected"])
  console.log(line, ":", new RegExp(line,"i").test(body) ? "shown" : "MISSING");
await p.screenshot({path:"auto-trade-conn.png", fullPage:true});
await b.close();
