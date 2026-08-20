import { chromium } from "playwright";
const b = await chromium.launch();
const pg = await b.newPage({ viewport: { width: 1700, height: 1200 } });
await pg.goto("https://apex-django.dashboardpack.com/", { waitUntil: "networkidle", timeout: 60000 });
const u = pg.locator('input[type="text"], input[name="username"]').first();
if (await u.count()) {
  await u.fill("demo");
  await pg.locator('input[type="password"]').first().fill("ApexShowcase!2026");
  await pg.locator('button[type="submit"], input[type="submit"]').first().click();
  await pg.waitForLoadState("networkidle").catch(()=>{}); await pg.waitForTimeout(2500);
}
// switch to their dark mode too, since the operator's screenshot is dark
const out = await pg.evaluate(() => {
  const g=(el,...p)=>el?Object.fromEntries(p.map(k=>[k,getComputedStyle(el)[k]])):null;
  const T=e=>(e&&typeof e.innerText==="string")?e.innerText:"";
  const card=[...document.querySelectorAll("div")].find(d=>/Total Revenue/.test(T(d))
    && d.querySelector("svg") && d.getBoundingClientRect().width < 500);
  if(!card) return {none:true};
  const label=[...card.querySelectorAll("*")].find(e=>T(e).trim()==="Total Revenue");
  const val=[...card.querySelectorAll("*")].find(e=>/^\$45,231/.test(T(e).trim()));
  const delta=[...card.querySelectorAll("*")].find(e=>/from last month/.test(T(e).trim())
    && e.children.length===0);
  const iconBox=card.querySelector("svg")?.closest("div,span");
  const spark=card.querySelector("svg:not(:first-child)") || card.querySelectorAll("svg")[1];
  return {
    card:{cls:card.className.slice(0,90), ...g(card,"backgroundColor","border","borderRadius","padding","boxShadow","gap")},
    label:g(label,"fontSize","fontWeight","color","letterSpacing","textTransform"),
    value:g(val,"fontSize","fontWeight","color","letterSpacing","lineHeight"),
    delta:{t:T(delta).trim(), ...g(delta,"fontSize","color","fontWeight")},
    iconBox:{cls:iconBox&&iconBox.className.slice(0,80), ...g(iconBox,"width","height","backgroundColor","borderRadius","color","display")},
    spark:spark&&{h:Math.round(spark.getBoundingClientRect().height), w:Math.round(spark.getBoundingClientRect().width)},
    cardW:Math.round(card.getBoundingClientRect().width), cardH:Math.round(card.getBoundingClientRect().height),
  };
});
console.log(JSON.stringify(out, null, 1));
await b.close();
