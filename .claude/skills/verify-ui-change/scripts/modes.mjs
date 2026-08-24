import {chromium} from 'playwright';
const b=await chromium.launch(); const p=await b.newPage({viewport:{width:1440,height:1000}});
const errs=[]; p.on('pageerror',e=>errs.push(String(e).slice(0,140)));
// NEVER networkidle: this page polls every 4s so it is never idle
await p.goto('http://localhost:8503/backtest',{waitUntil:'domcontentloaded',timeout:120000});
await p.waitForTimeout(8000);
for (const name of ['BACKTEST','UPDATE BACKTEST']) {
  const btn=p.locator('button',{hasText:new RegExp(`^${name}$`)}).first();
  const n=await btn.count();
  const tip=n? await btn.evaluate(e=>e.closest('span[title]')?.getAttribute('title')||'(no tooltip)') : '(button missing)';
  console.log(`${name}: ${n?'present':'MISSING'} — tooltip: ${tip}`);
}
const labels=await p.evaluate(()=>[...document.querySelectorAll('b')].map(e=>e.textContent.trim())
  .filter(t=>/grid|update/i.test(t)));
console.log('progress labels on page:', labels);
console.log('page errors:', errs);
const card=p.locator('div').filter({hasText:/^Backtest/}).first();
await p.locator('h3',{hasText:'Backtest'}).first().evaluate(e=>e.scrollIntoView());
await p.waitForTimeout(400);
await p.screenshot({path:'modes.png',clip:{x:250,y:120,width:1150,height:430}});
console.log('shot: modes.png');
await b.close();
