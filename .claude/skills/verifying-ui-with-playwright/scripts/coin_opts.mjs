import { chromium } from "playwright";
const b = await chromium.launch(); const p = await b.newPage({viewport:{width:1680,height:1200}});
await p.goto("http://localhost:8503", {waitUntil:"networkidle"}); await p.waitForTimeout(9000);
await p.locator('label', {hasText: "Backtest 2"}).first().click(); await p.waitForTimeout(12000);
// open the Daily grid coins multiselect and count options
await p.locator('.st-key-bt2_coins [data-testid="stMultiSelect"] input').click();
await p.waitForTimeout(2000);
const n = await p.locator('li[role="option"]').count();
console.log("daily-grid coin options visible:", n);
const first = await p.locator('li[role="option"]').first().innerText().catch(()=>"-");
console.log("first option:", first);
await p.keyboard.press("Escape");
await p.screenshot({path:"coin-opts.png"});
await b.close();
