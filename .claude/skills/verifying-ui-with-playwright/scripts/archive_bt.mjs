import { chromium } from "playwright";
const b = await chromium.launch(); const p = await b.newPage({viewport:{width:1680,height:1200}});
await p.goto("http://localhost:8503", {waitUntil:"networkidle"}); await p.waitForTimeout(9000);
await p.locator('label', {hasText: "Back Test"}).first().click(); await p.waitForTimeout(12000);

// pick APEX_USDT in the archive-backtest coin select (key mdbt_coin)
await p.locator('.st-key-mdbt_coin [data-testid="stSelectbox"]').click();
await p.waitForTimeout(1000);
await p.locator('li', {hasText: "APEX_USDT"}).first().click();
await p.waitForTimeout(2000);
// timeframe 1h
await p.locator('.st-key-mdbt_tf [data-testid="stSelectbox"]').click();
await p.waitForTimeout(1000);
await p.locator('li').filter({hasText: /^1h$/}).first().click();
await p.waitForTimeout(2000);
// dates: previous month
await p.locator('.st-key-mdbt_win [data-testid="stSelectbox"]').click();
await p.waitForTimeout(1000);
await p.locator('li', {hasText: "Previous month"}).first().click();
await p.waitForTimeout(2000);

await p.locator('[data-testid="stButton"] button').filter({hasText:/^BACKTEST$/}).click();
// grid measured ~8s for 1 coin x 1h; allow slack for streamlit rerun
await p.waitForTimeout(60000);
const body = await p.innerText("body");
for (const t of ["combinations tested", "OPEN THE REPORT", "saved to the database"])
  console.log(t, ":", /combinations tested/i.test(body) && body.includes(t) ? "shown" : (body.includes(t) ? "shown" : "MISSING"));
const href = await p.locator('a', {hasText: "OPEN THE REPORT"}).first().getAttribute("href").catch(()=>null);
console.log("report href:", href);
await p.screenshot({path:"archive-bt.png", fullPage:true});
await b.close();
