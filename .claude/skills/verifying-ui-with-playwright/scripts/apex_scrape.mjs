import { chromium } from "playwright";
const b = await chromium.launch();
const pg = await b.newPage({ viewport: { width: 1600, height: 1100 } });
await pg.goto("https://apex-django.dashboardpack.com/", { waitUntil: "networkidle", timeout: 60000 });
console.log("title:", await pg.title());
// the page publishes its own demo credentials
const u = pg.locator('input[name="username"], input#username, input[type="text"]').first();
const p = pg.locator('input[name="password"], input#password, input[type="password"]').first();
if (await u.count()) {
  await u.fill("demo"); await p.fill("ApexShowcase!2026");
  await pg.locator('button[type="submit"], input[type="submit"]').first().click();
  await pg.waitForLoadState("networkidle", { timeout: 60000 }).catch(()=>{});
  await pg.waitForTimeout(3000);
}
console.log("after login:", pg.url());
await pg.screenshot({ path: "apex-dash.png", fullPage: false });

const styles = await pg.evaluate(() => {
  const cs = (el, props) => { if (!el) return null; const s = getComputedStyle(el);
    return Object.fromEntries(props.map(p => [p, s[p]])); };
  const body = cs(document.body, ["backgroundColor","color","fontFamily","fontSize"]);
  const table = document.querySelector("table");
  const th = table && table.querySelector("th");
  const td = table && table.querySelector("tbody td");
  const tr = table && table.querySelector("tbody tr");
  const card = document.querySelector(".card, .panel, .box, [class*=card]");
  const cardHdr = card && card.querySelector("[class*=header], [class*=title], h1,h2,h3,h4,h5");
  const btn = document.querySelector("button, .btn, a.btn");
  const nav = document.querySelector("nav, aside, .sidebar, [class*=sidebar]");
  return {
    body,
    table: cs(table, ["borderCollapse","fontSize","width","backgroundColor"]),
    th: cs(th, ["backgroundColor","color","fontSize","fontWeight","letterSpacing","textTransform","padding","borderBottom","textAlign"]),
    td: cs(td, ["padding","fontSize","color","borderBottom","fontVariantNumeric"]),
    tr: cs(tr, ["backgroundColor","borderBottom"]),
    card: cs(card, ["backgroundColor","border","borderRadius","boxShadow","padding","marginBottom"]),
    cardHdr: cs(cardHdr, ["fontSize","fontWeight","letterSpacing","textTransform","color","padding","borderBottom"]),
    btn: cs(btn, ["backgroundColor","color","borderRadius","padding","fontSize","fontWeight","border"]),
    nav: cs(nav, ["backgroundColor","width","borderRight","color"]),
    cardClass: card && card.className, tableClass: table && table.className,
    fonts: [...new Set([...document.querySelectorAll("body,h1,h2,h3,td,th,button")]
      .map(e => getComputedStyle(e).fontFamily))].slice(0,6),
    cssVars: (() => { const r = getComputedStyle(document.documentElement); const out={};
      for (const s of document.styleSheets) { try { for (const rule of s.cssRules||[]) {
        if (rule.style) for (const n of rule.style) if (n.startsWith("--")) out[n]=r.getPropertyValue(n).trim();
      } } catch(e){} } return out; })(),
  };
});
console.log(JSON.stringify(styles, null, 1).slice(0, 4000));
await b.close();
