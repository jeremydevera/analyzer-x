import { chromium } from "playwright";
const b = await chromium.launch(); const p = await b.newPage({viewport:{width:1680,height:1400}});
await p.goto("http://localhost:8503", {waitUntil:"networkidle", timeout: 60000}); await p.waitForTimeout(12000);
// Auto Trade is the landing page
let body = await p.innerText("body");
const bad = body.match(/\b\d{2}-\d{2} \d{2}:\d{2}\b/g) || [];
const iso = body.match(/\b\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}\b/g) || [];
const good = body.match(/[A-Z][a-z]{2} \d{1,2}, \d{4} \d{1,2}:\d{2}[AP]M/g) || [];
console.log("AutoTrade bad MM-DD HH:MM:", bad.slice(0,3), "| ISO:", iso.slice(0,3), "| good:", good.slice(0,2), `(${good.length})`);
await p.getByText("Backtest 2", {exact: true}).first().click(); await p.waitForTimeout(35000);
body = await p.innerText("body");
const bad2 = body.match(/\b\d{2}-\d{2} \d{2}:\d{2}\b/g) || [];
const iso2 = body.match(/\b\d{4}-\d{2}-\d{2}[ T]?\d{0,2}:?\d{0,2}\b/g) || [];
const good2 = body.match(/[A-Z][a-z]{2} \d{1,2}, \d{4}( \d{1,2}:\d{2}[AP]M)?/g) || [];
console.log("Backtest2 bad:", bad2.slice(0,3), "| ISO:", iso2.slice(0,4), "| good:", good2.slice(0,3), `(${good2.length})`);
await p.screenshot({path:"datefmt.png", fullPage:true});
await b.close();
