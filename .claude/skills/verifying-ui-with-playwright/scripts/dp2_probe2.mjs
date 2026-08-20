import { chromium } from "playwright";
const BASE = "https://zenith-shadcn.dashboardpack.com";
const b = await chromium.launch();
const pg = await b.newPage({ viewport: { width: 1600, height: 1000 } });
for (const p of ["/forms","/settings","/customers"]) {
  await pg.goto(BASE+p, { waitUntil: "networkidle", timeout: 60000 });
  await pg.waitForTimeout(3000);
  await pg.evaluate(async () => { for(let y=0;y<6000;y+=400){window.scrollTo(0,y); await new Promise(r=>setTimeout(r,80));} window.scrollTo(0,0); });
  await pg.waitForTimeout(2000);
  const info = await pg.evaluate(() => ({
    inputs: document.querySelectorAll('input').length,
    textarea: document.querySelectorAll('textarea').length,
    cb: document.querySelectorAll('[role=checkbox],input[type=checkbox],button[role=checkbox]').length,
    radio: document.querySelectorAll('[role=radio],input[type=radio]').length,
    sw: document.querySelectorAll('[role=switch]').length,
    labels: document.querySelectorAll('label').length,
    tabs: document.querySelectorAll('[role=tab]').length,
    prog: document.querySelectorAll('[role=progressbar]').length,
    txt: document.body.innerText.replace(/\n+/g,' | ').slice(0,900),
  }));
  console.log("=====", p, JSON.stringify(info,null,1));
}
await b.close();
