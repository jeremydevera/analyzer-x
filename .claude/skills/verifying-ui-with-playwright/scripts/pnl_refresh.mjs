import { chromium } from "playwright";
const b=await chromium.launch(); const p=await b.newPage({viewport:{width:1680,height:1200}});
await p.goto("http://localhost:8503",{waitUntil:"networkidle"}); await p.waitForTimeout(9000);
await p.locator('label',{hasText:"Auto Trade"}).first().click(); await p.waitForTimeout(7000);
const grab=async()=>{const t=await p.innerText("body");
  const m=t.match(/REAL PNL NOW \(LIVE\)\s*([-+\d,.]+)\s*USDT/i);
  const q=t.match(/PAPER PNL NOW\s*\(DEMO\)\s*([-+\d,.]+)\s*USDT/i);
  return [m?m[1]:"?", q?q[1]:"?"];};
for(let i=0;i<3;i++){const [r,pa]=await grab();
  console.log(`t+${i*6}s  real ${r}  paper ${pa}`); await p.waitForTimeout(6000);}
await b.close();
