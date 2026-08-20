import { chromium } from "playwright";
const b = await chromium.launch();
const pg = await b.newPage({ viewport: { width: 1800, height: 1400 } });
const errs = []; pg.on("pageerror", e => errs.push(String(e)));
await pg.goto("http://localhost:8503", { waitUntil: "networkidle" });
await pg.waitForTimeout(11000);
for (const page of ["Back Test", "Backtest 2"]) {
  let ok = false;
  for (let a=0;a<3;a++){
    await pg.locator('[data-testid="stRadio"] label').filter({ hasText: new RegExp("^"+page+"$") }).first().click({force:true});
    await pg.waitForTimeout(7000);
    if ((await pg.locator("text=/market data/i").count()) || (await pg.locator("button", {hasText:/^DOWNLOAD$/}).count())) { ok = true; break; }
  }
  const btns = await pg.locator("button").evaluateAll(ns=>ns.map(n=>n.innerText.trim()).filter(Boolean));
  const hasDl = btns.some(t=>/^DOWNLOAD$/i.test(t));
  const hasUp = btns.some(t=>/^UPDATE$/i.test(t));
  const hdr = await pg.locator(".ta-section").allInnerTexts().catch(()=>[]);
  console.log(`${page.padEnd(11)} reached=${ok}  DOWNLOAD=${hasDl}  UPDATE=${hasUp}`);
  console.log(`${" ".repeat(11)} sections: ${JSON.stringify(hdr.slice(0,4))}`);
  await pg.screenshot({ path: `bt-${page.replace(/\s+/g,"")}.png`, fullPage: false });
}
console.log("errors:", errs.length, errs.slice(0,2).join(" | "));
await b.close();
