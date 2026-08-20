import { chromium } from "playwright";
const b = await chromium.launch();
const pg = await b.newPage({ viewport: { width: 1800, height: 1600 } });
const errs = []; pg.on("pageerror", e => errs.push(String(e)));
await pg.goto("http://localhost:8503", { waitUntil: "networkidle" });
await pg.waitForTimeout(11000);
const night = pg.locator('input[aria-label="Night mode"]');
const nightBox = pg.locator('label').filter({ hasText: /Night mode/i }).first();
for (const theme of ["light","night"]) {
  if ((theme === "night") !== await night.isChecked()) {
    await nightBox.click({ force:true }); await pg.waitForTimeout(7000);
  }
  for (let a=0;a<4;a++){
    await pg.locator('[data-testid="stRadio"] label').filter({ hasText: /^Auto Trade$/ }).first().click({force:true});
    await pg.waitForTimeout(9000);
    if (await pg.locator('.an-svg').count()) break;
  }
  const v = await pg.evaluate(() => {
    const g=(el,...p)=>el?Object.fromEntries(p.map(k=>[k,getComputedStyle(el)[k]])):null;
    const root=getComputedStyle(document.documentElement);
    const svg=document.querySelector('.an-svg');
    const bars=[...document.querySelectorAll('.an-bar')];
    return {
      tok:{bg:root.getPropertyValue('--bg').trim(), panel:root.getPropertyValue('--panel').trim(),
           buy:root.getPropertyValue('--buy').trim(), sell:root.getPropertyValue('--sell').trim()},
      curve: svg ? {h:Math.round(svg.getBoundingClientRect().height),
                    w:Math.round(svg.getBoundingClientRect().width),
                    aria:svg.getAttribute('aria-label')} : null,
      panel:g(document.querySelector('.an-panel'),"backgroundColor","borderTopWidth","borderRadius","padding"),
      cap:document.querySelector('.an-cap')?.innerText.slice(0,150),
      bars:bars.length, firstBar:bars[0]?.innerText.replace(/\n/g," | "),
    };
  });
  console.log(`\n===== ${theme.toUpperCase()}`);
  console.log("tokens :", JSON.stringify(v.tok));
  console.log("curve  :", JSON.stringify(v.curve));
  console.log("panel  :", JSON.stringify(v.panel));
  console.log("caption:", v.cap);
  console.log("bars   :", v.bars, "| first:", v.firstBar);
  const p = pg.locator('.an-grid').first();
  await p.scrollIntoViewIfNeeded(); await pg.waitForTimeout(700);
  const bx = await p.boundingBox();
  await pg.screenshot({ path: `analyst-${theme}.png`, clip:{x:150,y:Math.max(0,bx.y-90),width:1620,height:430} });
}
console.log("\nerrors:", errs.length, errs.slice(0,2).join(" | "));
await b.close();
