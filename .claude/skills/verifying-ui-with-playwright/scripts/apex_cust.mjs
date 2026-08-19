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
await pg.goto("https://apex-django.dashboardpack.com/customers/", { waitUntil: "networkidle", timeout: 60000 });
await pg.waitForTimeout(3000);
console.log("url:", pg.url(), "| title:", await pg.title());
await pg.screenshot({ path: "apex-customers.png", fullPage: false });

const d = await pg.evaluate(() => {
  const g=(el,...p)=>el?Object.fromEntries(p.map(k=>[k,getComputedStyle(el)[k]])):null;
  const tb=document.querySelector("table");
  if(!tb) return {none:true, body:document.body.innerText.slice(0,400)};
  const card=tb.closest("[class*=rounded],[class*=card],[class*=border]");
  const hdrArea=card && card.querySelector("[class*=flex],[class*=header]");
  const ths=[...tb.querySelectorAll("thead th")];
  const firstRow=tb.querySelector("tbody tr");
  const tds=firstRow?[...firstRow.querySelectorAll("td")]:[];
  const pill=tb.querySelector("[class*=rounded-full],[class*=badge],span[class*=bg-]");
  const avatar=tb.querySelector("[class*=rounded-full][class*=w-],[class*=h-9]");
  const btn=card&&card.querySelector("button");
  const inp=card&&card.querySelector("input");
  return {
    card:g(card,"backgroundColor","border","borderRadius","boxShadow","padding","overflow"),
    hdrArea:g(hdrArea,"padding","borderBottom","display","gap"),
    table:g(tb,"fontSize","borderCollapse","width"),
    thead:g(tb.querySelector("thead"),"backgroundColor","position","top"),
    thStyles:ths.map(t=>({txt:t.innerText.trim(), ...g(t,"padding","fontSize","fontWeight","color","textAlign","textTransform","letterSpacing","whiteSpace","borderBottom")})).slice(0,9),
    tdStyles:tds.map(t=>({txt:t.innerText.trim().slice(0,26), ...g(t,"padding","fontSize","color","textAlign","borderBottom","verticalAlign")})).slice(0,9),
    tr:g(firstRow,"height","backgroundColor","borderBottom"),
    trHoverClass:firstRow&&firstRow.className,
    pill:pill&&{cls:pill.className,...g(pill,"backgroundColor","color","borderRadius","padding","fontSize","fontWeight","border")},
    avatar:avatar&&{cls:avatar.className,...g(avatar,"width","height","borderRadius","backgroundColor","fontSize","fontWeight")},
    btn:btn&&{txt:btn.innerText.trim(),...g(btn,"backgroundColor","color","borderRadius","padding","fontSize","fontWeight","border")},
    input:inp&&g(inp,"backgroundColor","borderRadius","border","padding","fontSize","width"),
    rows:tb.querySelectorAll("tbody tr").length,
    colCount:ths.length,
  };
});
console.log(JSON.stringify(d, null, 1).slice(0, 5200));
await b.close();
