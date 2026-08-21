import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage({viewport:{width:1512,height:1100}});
p.on('dialog', d => d.dismiss());
await p.goto('http://localhost:8503/trade', {waitUntil:'domcontentloaded'});
await p.waitForSelector('text=Strategies you have deployed', {timeout:60000});
await p.waitForTimeout(5000);
const el = p.locator('div.min-w-0').filter({ hasText: 'ladder $' }).first();
await el.screenshot({ path: '/tmp/books-col.png' });
await b.close(); console.log('shot');
