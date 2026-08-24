import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1600,height:700});
await p.goto('http://localhost:8503/?p=backtest-2', {waitUntil:'domcontentloaded', timeout:120000});
await p.waitForFunction(()=>document.querySelectorAll('[data-baseweb="select"]').length>0,{timeout:120000});
await p.waitForTimeout(3500);
// TIMEFRAMES has all five chosen -> its menu is the empty state
await p.locator('[data-baseweb="select"]').nth(1).click();
await p.waitForTimeout(1200);
await p.screenshot({path:'empty_fixed.png', clip:{x:700,y:330,width:900,height:280}});
console.log('shot ok');
await b.close();
