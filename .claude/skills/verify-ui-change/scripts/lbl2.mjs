import {chromium} from 'playwright';
const b=await chromium.launch(); const p=await b.newPage({viewport:{width:1800,height:1400}});
await p.goto('http://localhost:8503/trade',{waitUntil:'domcontentloaded',timeout:120000});
await p.waitForTimeout(11000);
// the STRATEGIES table: the row that also carries TP/SL and the book toggles
const row = p.locator('tr').filter({hasText:'NEQMY7RS'}).filter({hasText:'DEMO'}).first();
await row.scrollIntoViewIfNeeded(); await p.waitForTimeout(500);
const box = await row.boundingBox();
await p.screenshot({path:'lbl2.png', clip:{x:0, y:Math.max(0,box.y-150), width:1200, height:330}});
console.log('captured the strategies row');
await b.close();
