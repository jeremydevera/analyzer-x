import {chromium} from 'playwright';
const b=await chromium.launch(); const p=await b.newPage({viewport:{width:1700,height:1250}});
await p.goto('http://localhost:8503/backtest',{waitUntil:'domcontentloaded',timeout:120000});
await p.waitForTimeout(10000);
const btn = p.locator('button', {hasText:'SWITCH TO GITHUB ACTIONS'}).first();
const n = await btn.count();
console.log('button present:', n>0);
if(n){
  console.log('disabled:', await btn.isDisabled());
  console.log('tooltip :', (await btn.evaluate(e=>e.closest('span[title]')?.getAttribute('title')||'')).slice(0,120));
}
const t = await p.evaluate(()=>document.body.innerText);
console.log('reason line:', (t.match(/SWITCH TO GITHUB ACTIONS is disabled:[^\n]*/)||['(none)'])[0].slice(0,150));
console.log('cores line :', (t.match(/\d+ OF \d+ CORES WORKING/i)||['(none)'])[0]);
const row = p.locator('div').filter({hasText:/SWITCH TO GITHUB ACTIONS/}).last();
const box = await btn.boundingBox();
await p.screenshot({path:'btn.png', clip:{x:0, y:Math.max(0,box.y-40), width:1450, height:200}});
await b.close();
