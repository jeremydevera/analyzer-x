import {chromium} from 'playwright';
const b=await chromium.launch(); const p=await b.newPage({viewport:{width:1700,height:1300}});
// NEVER networkidle: this page polls
await p.goto('http://localhost:8503/trade',{waitUntil:'domcontentloaded',timeout:120000});
await p.waitForTimeout(11000);
const rows = await p.evaluate(()=>{
  const tr=[...document.querySelectorAll('tr')].filter(r=>/NEQMY7RS|F2S7J87Z|3RAUB3WW/.test(r.innerText));
  return tr.map(r=>r.innerText.split('\n').slice(0,4).join(' | '));
});
console.log('the rows in question:');
rows.forEach(r=>console.log('   '+r.slice(0,110)));
const el = await p.locator('tr', {hasText:'NEQMY7RS'}).first();
await el.scrollIntoViewIfNeeded(); await p.waitForTimeout(400);
const box = await el.boundingBox();
await p.screenshot({path:'lbl.png', clip:{x:Math.max(0,box.x-10), y:Math.max(0,box.y-120), width:Math.min(1000,box.width+20), height:280}});
await b.close();
