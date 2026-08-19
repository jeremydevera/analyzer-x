import { chromium } from "playwright";
const b=await chromium.launch(); const p=await b.newPage({viewport:{width:1680,height:1400}});
await p.goto("http://localhost:8503",{waitUntil:"networkidle"}); await p.waitForTimeout(9000);
await p.locator('label',{hasText:"Auto Trade"}).first().click(); await p.waitForTimeout(8000);
const dfs=p.locator('[data-testid="stDataFrame"]');
console.log("tables:", await dfs.count());
for (let i=0;i<await dfs.count();i++){
  const t=(await dfs.nth(i).innerText()).split("\n").slice(0,14).join(" | ");
  console.log(`table ${i}: ${t}`);
}
await p.screenshot({path:"pos-time.png", clip:{x:890,y:900,width:790,height:500}});
await b.close();
