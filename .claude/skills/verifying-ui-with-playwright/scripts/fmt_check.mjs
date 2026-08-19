import { chromium } from "playwright";
const b=await chromium.launch(); const p=await b.newPage({viewport:{width:1680,height:1400}});
await p.goto("http://localhost:8503",{waitUntil:"networkidle"}); await p.waitForTimeout(9000);
await p.locator('label',{hasText:"Auto Trade"}).first().click(); await p.waitForTimeout(8000);
const body=await p.innerText("body");
const m=body.match(/[A-Z][a-z]{2} \d{1,2}, \d{4} \(\d{1,2}:\d{2}[AP]M\)/g);
console.log("date cells found:", m ? [...new Set(m)].slice(0,6) : "NONE");
await p.screenshot({path:"fmt.png", clip:{x:890,y:1080,width:790,height:320}});
await b.close();
