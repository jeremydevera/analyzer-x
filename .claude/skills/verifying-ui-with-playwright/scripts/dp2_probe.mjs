import { chromium } from "playwright";
const BASE = "https://zenith-shadcn.dashboardpack.com";
const b = await chromium.launch();
const pg = await b.newPage({ viewport: { width: 1600, height: 1000 } });
for (const p of ["/forms","/customers","/charts","/billing","/settings"]) {
  try {
    const r = await pg.goto(BASE+p, { waitUntil: "domcontentloaded", timeout: 45000 });
    await pg.waitForTimeout(2500);
    const info = await pg.evaluate(() => ({
      title: document.title,
      h1: [...document.querySelectorAll('h1,h2')].slice(0,3).map(e=>e.textContent.trim().slice(0,40)),
      inputs: document.querySelectorAll('input').length,
      combobox: document.querySelectorAll('[role=combobox]').length,
      haspopup: document.querySelectorAll('button[aria-haspopup]').length,
      textarea: document.querySelectorAll('textarea').length,
      cb: document.querySelectorAll('[role=checkbox],input[type=checkbox]').length,
      sw: document.querySelectorAll('[role=switch]').length,
      labels: document.querySelectorAll('label').length,
      tablist: document.querySelectorAll('[role=tablist]').length,
      tabs: document.querySelectorAll('[role=tab]').length,
      tables: document.querySelectorAll('table').length,
      btns: document.querySelectorAll('button').length,
      prog: document.querySelectorAll('[role=progressbar]').length,
      bodyLen: document.body.innerText.length,
    }));
    console.log(p, r.status(), JSON.stringify(info));
  } catch(e) { console.log(p, "ERR", String(e).slice(0,120)); }
}
await b.close();
