import { chromium } from "playwright";
const b = await chromium.launch();
const pg = await b.newPage({ viewport: { width: 1800, height: 1300 } });
const errs = []; pg.on("pageerror", e => errs.push(String(e)));
await pg.goto("http://localhost:8503", { waitUntil: "networkidle" });
await pg.waitForTimeout(11000);
const PAGES = ["New Crypto", "Stocks", "Auto Trade", "Back Test", "LLM Models"];
const night = pg.locator('input[aria-label="Night mode"]');
const nightBox = pg.locator('label').filter({ hasText: /Night mode/i }).first();

const probe = async () => await pg.evaluate(() => {
  const g=(el,...p)=>el?Object.fromEntries(p.map(k=>[k,getComputedStyle(el)[k]])):null;
  const root=getComputedStyle(document.documentElement);
  const app=document.querySelector('[data-testid="stAppViewContainer"]');
  const btn=document.querySelector('.stButton>button');
  const th=document.querySelector('[data-testid="stTable"] thead th, .stMarkdown thead th');
  const wrap=document.querySelector('[data-testid="stVerticalBlockBorderWrapper"]');
  return {
    tok:{bg:root.getPropertyValue('--bg').trim(), accent:root.getPropertyValue('--accent').trim(),
         r:root.getPropertyValue('--r').trim(), border:root.getPropertyValue('--border').trim()},
    app:g(app,"backgroundColor"), btn:g(btn,"borderRadius"),
    th:th?g(th,"textTransform","fontWeight","padding","backgroundColor"):null,
    wrap:g(wrap,"borderRadius","backgroundColor"),
  };
});

for (const theme of ["light","night"]) {
  if ((theme === "night") !== await night.isChecked()) {
    await nightBox.click({ force: true }); await pg.waitForTimeout(7000);
  }
  console.log(`\n================ ${theme.toUpperCase()} ================`);
  for (const name of PAGES) {
    for (let a=0;a<3;a++){
      await pg.locator('[data-testid="stRadio"] label').filter({ hasText: new RegExp("^"+name+"$") }).first().click({ force: true });
      await pg.waitForTimeout(name === "Auto Trade" ? 9000 : 5000);
      const t = await pg.locator("h1,h2").first().innerText().catch(()=>"");
      if (t) break;
    }
    const v = await probe();
    console.log(`${name.padEnd(11)} tokens bg=${v.tok.bg} accent=${v.tok.accent} r=${v.tok.r}`);
    console.log(`${" ".repeat(11)} page=${v.app.backgroundColor} card-radius=${v.wrap?.borderRadius} btn-radius=${v.btn?.borderRadius}`
      + (v.th ? ` th=${v.th.textTransform}/${v.th.fontWeight} pad ${v.th.padding}` : " (no html table on this page)"));
    await pg.screenshot({ path: `apx-${theme}-${name.replace(/\s+/g,"")}.png`, fullPage: false });
  }
}
console.log("\nerrors:", errs.length, errs.slice(0,3).join(" | "));
await b.close();
