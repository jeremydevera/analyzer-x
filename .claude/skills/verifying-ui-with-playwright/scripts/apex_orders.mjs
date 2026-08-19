import { chromium } from "playwright";
const b = await chromium.launch();
const pg = await b.newPage({ viewport: { width: 1700, height: 1400 } });
await pg.goto("https://apex-django.dashboardpack.com/", { waitUntil: "networkidle", timeout: 60000 });
const u = pg.locator('input[type="text"], input[name="username"]').first();
if (await u.count()) {
  await u.fill("demo");
  await pg.locator('input[type="password"]').first().fill("ApexShowcase!2026");
  await pg.locator('button[type="submit"], input[type="submit"]').first().click();
  await pg.waitForLoadState("networkidle").catch(()=>{}); await pg.waitForTimeout(2000);
}
await pg.goto("https://apex-django.dashboardpack.com/orders/", { waitUntil: "networkidle", timeout: 60000 });
await pg.waitForTimeout(3000);
console.log("url:", pg.url());
await pg.screenshot({ path: "apex-orders.png", fullPage: false });

const d = await pg.evaluate(() => {
  const g=(el,...p)=>el?Object.fromEntries(p.map(k=>[k,getComputedStyle(el)[k]])):null;
  const tb=document.querySelector("table");
  const ths=[...tb.querySelectorAll("thead th")].map(t=>t.innerText.trim().replace(/\s+/g," "));
  const rows=[...tb.querySelectorAll("tbody tr")].slice(0,3).map(tr =>
    [...tr.querySelectorAll("td")].map(td => ({
      t: td.innerText.trim().replace(/\s+/g," ").slice(0,34),
      align: getComputedStyle(td).textAlign,
      html: td.innerHTML.replace(/\s+/g," ").slice(0,150),
    })));
  // every pill on the page and its colours
  const pills=[...document.querySelectorAll('[class*="rounded-full"]')]
    .filter(e=>e.innerText.trim() && e.innerText.trim().length<20)
    .slice(0,10).map(e=>({txt:e.innerText.trim(), cls:e.className,
      ...g(e,"backgroundColor","color","borderRadius","padding","fontSize","fontWeight","border")}));
  // toolbar above the table
  const bar=tb.closest("[class*=rounded]")?.previousElementSibling;
  const btns=[...document.querySelectorAll("button")].slice(0,10)
    .map(x=>({t:x.innerText.trim().replace(/\s+/g," ").slice(0,22), ...g(x,"backgroundColor","color","borderRadius","padding","fontSize","fontWeight","border")}));
  return { ths, rows, pills, btns, bar: bar && bar.innerText.replace(/\s+/g," ").slice(0,160),
           colCount: ths.length, rowCount: tb.querySelectorAll("tbody tr").length };
});
console.log("HEADERS:", JSON.stringify(d.ths));
console.log("\nFIRST ROWS:");
for (const r of d.rows) console.log("  " + JSON.stringify(r.map(c=>`${c.t}[${c.align}]`)));
console.log("\nROW 1 CELL HTML:");
for (const c of d.rows[0]) console.log("   " + c.html);
console.log("\nPILLS:");
for (const p of d.pills) console.log("  " + JSON.stringify(p));
console.log("\nBUTTONS:");
for (const x of d.btns) if (x.t) console.log("  " + JSON.stringify(x));
console.log("\ntoolbar:", d.bar, "| rows:", d.rowCount, "cols:", d.colCount);
await b.close();
