import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1600,height:900});
await p.goto('http://localhost:8503/trade', {waitUntil:'networkidle', timeout:120000});
await p.waitForTimeout(3500);
await p.screenshot({path:'bell_header.png', clip:{x:1150,y:0,width:450,height:110}});
const grid = await p.$('table');
if (grid) { await grid.scrollIntoViewIfNeeded(); await p.waitForTimeout(500);
            await grid.screenshot({path:'bell_grid.png'}); }
console.log('shots ok');
await b.close();
