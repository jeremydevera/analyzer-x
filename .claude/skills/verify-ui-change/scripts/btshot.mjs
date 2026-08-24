import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1500,height:900});
await p.goto('http://localhost:8503/backtest', {waitUntil:'networkidle', timeout:120000});
await p.waitForTimeout(4500);
const el = await p.evaluateHandle(() => [...document.querySelectorAll('h3')]
  .find(h => h.innerText.trim() === 'Backtest history')?.closest('div'));
const box = el.asElement();
if (box) { await box.scrollIntoViewIfNeeded(); await p.waitForTimeout(400);
           await box.screenshot({path:'bt_history_bottom.png'}); console.log('ok'); }
await b.close();
