import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1900,height:1100});
await p.goto('http://localhost:8503/app/static/bt/openrow-mid.html',
             {waitUntil:'domcontentloaded', timeout:120000});
await p.waitForTimeout(2500);
await p.selectOption('#show', 'all'); await p.waitForTimeout(2000);
await p.fill('#fid', '3M3CRXP8'); await p.waitForTimeout(3000);
const box = await p.$('.logbox');
await box.evaluate(el => el.scrollTop = el.scrollHeight);
await p.waitForTimeout(400);
await box.screenshot({path:'footer_fixed.png'});
console.log('shot ok');
await b.close();
