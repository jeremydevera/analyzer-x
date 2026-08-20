import { chromium } from "playwright";
const b = await chromium.launch();
const pg = await b.newPage({ viewport: { width: 1800, height: 1700 } });
const errs = []; pg.on("pageerror", e => errs.push(String(e)));
await pg.goto("http://localhost:8503", { waitUntil: "networkidle" });
await pg.waitForTimeout(12000);
const side = pg.locator('[data-testid="stSidebar"]');
for (let a=0;a<3;a++){
  const btn = side.locator("button", { hasText: /^Auto Trade$/ }).first();
  if (await btn.count() && await btn.isVisible()) { await btn.click({force:true}); await pg.waitForTimeout(10000); }
  if (await pg.locator('.mv-hero').count()) break;
}
const v = await pg.evaluate(() => {
  const g=(el,...p)=>el?Object.fromEntries(p.map(k=>[k,getComputedStyle(el)[k]])):null;
  const hero=document.querySelector('.mv-hero');
  const rows=document.querySelectorAll('.mv-row:not(.hd):not(.ft)');
  return {
    hero: hero && {h:Math.round(hero.getBoundingClientRect().height),
      value:hero.querySelector('.v')?.innerText, badge:hero.querySelector('.badge')?.innerText,
      delta:hero.querySelector('.d')?.innerText.replace(/\n/g," "), hasCurve:!!hero.querySelector('svg')},
    cells:[...document.querySelectorAll('.mv-cell')].map(c=>c.innerText.replace(/\n/g," | ")),
    posHeader:document.querySelector('.mv-row.hd')?.innerText.replace(/\n/g," | "),
    posRows:rows.length,
    firstRow:rows[0]?.innerText.replace(/\n/g," | "),
    rings:document.querySelectorAll('.mv-ring').length,
    strategies:document.querySelectorAll('.mv-str > div').length - 1,
    heroFont:g(hero?.querySelector('.v'),"fontSize","fontWeight","letterSpacing"),
    widgetsInTable:document.querySelectorAll('.mv-panel button, .mv-panel input').length,
  };
});
console.log(JSON.stringify(v, null, 1));
console.log("errors:", errs.length, errs.slice(0,2).join(" | "));
await pg.screenshot({ path: "modern-full.png", fullPage: false });
await b.close();
