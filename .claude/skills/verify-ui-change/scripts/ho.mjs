import {chromium} from 'playwright';
const b=await chromium.launch(); const p=await b.newPage({viewport:{width:1600,height:1200}});
// NEVER networkidle: this page polls
await p.goto('http://localhost:8503/backtest',{waitUntil:'domcontentloaded',timeout:120000});
await p.waitForTimeout(10000);
const btn = p.locator('button', {hasText:'SWITCH TO GITHUB ACTIONS'}).first();
console.log('button present:', await btn.count() > 0);
if (await btn.count()) {
  const tip = await btn.evaluate(e=>e.closest('span[title]')?.getAttribute('title') || '(none)');
  console.log('tooltip:', tip.slice(0,150));
  const box = await btn.boundingBox();
  await p.screenshot({path:'ho.png', clip:{x:Math.max(0,box.x-360), y:Math.max(0,box.y-30), width:1150, height:150}});
}
console.log('buttons on the row:', (await p.locator('button').allInnerTexts()).filter(t=>/BACKTEST|STOP|GITHUB/i.test(t)).join(' | '));
await b.close();
