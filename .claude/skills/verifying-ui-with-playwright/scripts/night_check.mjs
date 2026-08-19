import { chromium } from "playwright";
const b = await chromium.launch(); const p = await b.newPage({viewport:{width:1680,height:1200}});
await p.goto("http://localhost:8503", {waitUntil:"networkidle"}); await p.waitForTimeout(9000);
await p.locator('label', {hasText: "Auto Trade"}).first().click(); await p.waitForTimeout(5000);
await p.screenshot({path:"tiles-day.png", fullPage:false});
await p.locator('[data-testid="stToggle"], [data-baseweb="checkbox"]').filter({hasText:/Night mode/}).locator('label,div').first().click().catch(async()=>{
  await p.getByText("Night mode").click();
});
await p.waitForTimeout(4000);
const bg = await p.evaluate(()=>getComputedStyle(document.querySelector('[data-testid="stAppViewContainer"]')).backgroundColor);
console.log("night bg:", bg);
await p.screenshot({path:"tiles-night.png", fullPage:false});
await b.close();
