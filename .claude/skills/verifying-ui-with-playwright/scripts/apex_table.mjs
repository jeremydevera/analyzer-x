import { chromium } from "playwright";
const b = await chromium.launch();
const pg = await b.newPage({ viewport: { width: 1600, height: 1200 } });
await pg.goto("https://apex-django.dashboardpack.com/", { waitUntil: "networkidle", timeout: 60000 });
const u = pg.locator('input[type="text"], input[name="username"]').first();
if (await u.count()) {
  await u.fill("demo");
  await pg.locator('input[type="password"]').first().fill("ApexShowcase!2026");
  await pg.locator('button[type="submit"], input[type="submit"]').first().click();
  await pg.waitForLoadState("networkidle").catch(()=>{}); await pg.waitForTimeout(2500);
}
// a page that is mostly TABLE
for (const name of ["Orders", "Customers", "Invoices"]) {
  const l = pg.locator("a", { hasText: new RegExp("^"+name+"$") }).first();
  if (await l.count()) { await l.click(); await pg.waitForTimeout(2500); break; }
}
console.log("url:", pg.url());
const t = pg.locator("table").first();
if (await t.count()) {
  await t.scrollIntoViewIfNeeded();
  const s = await pg.evaluate(() => {
    const g = (el, ...p) => el ? Object.fromEntries(p.map(k => [k, getComputedStyle(el)[k]])) : null;
    const tb = document.querySelector("table");
    const th = tb.querySelector("thead th"), td = tb.querySelector("tbody td");
    const tr = tb.querySelector("tbody tr");
    const wrap = tb.closest("[class*=card],[class*=rounded],div");
    const badge = document.querySelector("[class*=badge],[class*=pill],span[class*=rounded-full]");
    return {
      thead: g(tb.querySelector("thead"), "backgroundColor","borderBottom"),
      th: g(th, "color","fontSize","fontWeight","letterSpacing","textTransform","padding","textAlign","borderBottom","whiteSpace"),
      td: g(td, "color","fontSize","padding","borderBottom","verticalAlign","fontVariantNumeric"),
      tr: g(tr, "backgroundColor","borderBottom","height"),
      wrap: g(wrap, "backgroundColor","border","borderRadius","boxShadow","overflow","padding"),
      badge: badge && {cls: badge.className, ...g(badge,"backgroundColor","color","borderRadius","padding","fontSize","fontWeight")},
      rowCount: tb.querySelectorAll("tbody tr").length,
    };
  });
  console.log(JSON.stringify(s, null, 1));
  const bx = await t.boundingBox();
  await pg.screenshot({ path: "apex-table.png", clip: { x: Math.max(0,bx.x-24), y: Math.max(0,bx.y-90), width: Math.min(1560, bx.width+48), height: 520 } });
}
await b.close();
