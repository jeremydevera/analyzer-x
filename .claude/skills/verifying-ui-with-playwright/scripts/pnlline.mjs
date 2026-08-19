import { chromium } from 'playwright';
const b = await chromium.launch();
const p = await b.newPage({viewport:{width:1500,height:1100}});
const errs=[]; p.on('pageerror',e=>errs.push(String(e)));
await p.goto('http://localhost:8503',{waitUntil:'networkidle'});
await p.waitForTimeout(9000);
await p.getByText('Auto Trade',{exact:true}).first().click();
await p.waitForTimeout(12000);
console.log('JS errors:', errs.length?errs:'none');
const el = p.getByText(/today.s real closes/i).first();
if (await el.count()) {
  console.log('LINE:', (await el.innerText()).replace(/\n/g,' '));
  const bb = await el.boundingBox();
  console.log('at x=',Math.round(bb.x),'y=',Math.round(bb.y));
  await el.scrollIntoViewIfNeeded(); await p.waitForTimeout(800);
} else console.log('LINE NOT FOUND');
await p.screenshot({path:'/tmp/pnlline.png'});
console.log('h-overflow:', await p.evaluate(()=>document.documentElement.scrollWidth-document.documentElement.clientWidth));
await b.close();
