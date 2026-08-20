import { chromium } from "playwright";
const b = await chromium.launch(); const p = await b.newPage({viewport:{width:1680,height:1400}});
await p.goto("http://localhost:8503", {waitUntil:"networkidle", timeout: 60000}); await p.waitForTimeout(12000);
const navs = await p.locator('label').allInnerTexts();
console.log("nav labels seen:", navs.filter(t=>t.trim()).slice(0,12).join(" | "));
await p.screenshot({path:"nav-state.png", fullPage:true});
await b.close();
