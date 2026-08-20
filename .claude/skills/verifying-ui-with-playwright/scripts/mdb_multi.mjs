import { chromium } from "playwright";
const b = await chromium.launch(); const p = await b.newPage({viewport:{width:1680,height:1200}});
await p.goto("http://localhost:8503", {waitUntil:"networkidle"}); await p.waitForTimeout(9000);
await p.locator('label', {hasText: "Backtest 2"}).first().click(); await p.waitForTimeout(12000);
const chips = await p.locator('.st-key-mdb_coins [data-testid="stMultiSelect"] span[data-baseweb="tag"]').allInnerTexts();
console.log("default coin chips:", chips.map(c=>c.trim()).join(", "));
const tfchips = await p.locator('.st-key-mdb_tfs [data-testid="stMultiSelect"] span[data-baseweb="tag"]').allInnerTexts();
console.log("default tf chips:", tfchips.map(c=>c.trim()).join(", "));
// prove full list searchable: add BTC_USDT
const inp = p.locator('.st-key-mdb_coins [data-testid="stMultiSelect"] input');
await inp.click(); await inp.fill("BTC_USDT"); await p.waitForTimeout(1200);
await p.locator('li[role="option"]', {hasText: "BTC_USDT"}).first().click();
await p.waitForTimeout(1500);
const after = await p.locator('.st-key-mdb_coins [data-testid="stMultiSelect"] span[data-baseweb="tag"]').count();
console.log("chips after adding BTC_USDT:", after);
await p.screenshot({path:"mdb-multi.png"});
await b.close();
