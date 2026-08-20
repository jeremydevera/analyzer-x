import { chromium } from "playwright";
const b = await chromium.launch(); const p = await b.newPage({viewport:{width:1680,height:1400}});
await p.goto("http://localhost:8503", {waitUntil:"networkidle"}); await p.waitForTimeout(12000);
await p.locator('label', {hasText: "Backtest 2"}).first().click(); await p.waitForTimeout(40000);
for (const k of ["mdb_coins","mdbt_coins","bt2_coins"]) {
  const n = await p.locator(`.st-key-${k} span[data-baseweb="tag"]`).count();
  console.log(k, "selected chips:", n);
}
await p.screenshot({path:"empty-defaults.png", fullPage:true});
await b.close();
