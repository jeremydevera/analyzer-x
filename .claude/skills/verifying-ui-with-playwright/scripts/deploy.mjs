import { chromium } from 'playwright';
const b = await chromium.launch();
const p = await b.newPage({viewport:{width:1500,height:1200}});
const errs=[]; p.on('pageerror',e=>errs.push(String(e)));
await p.goto('http://localhost:8503',{waitUntil:'networkidle'});
await p.waitForTimeout(9000);
await p.getByText('Auto Trade',{exact:true}).first().click();
await p.waitForTimeout(15000);
console.log('JS errors:', errs.length?errs:'none');
const txt = await p.locator('body').innerText();
for (const name of ['Momentum 15 (4h) · TP 4.5% — PI','ICT fair value gap (4h) · TP 4.5%',
                    'Trend 50 (4h)','Momentum 15 (1h) · TP 2.4% — GOLD']) {
  console.log('tile present:', name.slice(0,34), txt.includes(name.slice(0,28)));
}
console.log('sizing control:', txt.includes('Position sizing'));
console.log('flat selected :', await p.locator('input[type=radio]').first().isChecked());
console.log('flat worst-case caption:', /flat worst case/i.test(txt));
// which tiles are ticked
const boxes = p.locator('[data-testid="stCheckbox"]');
const n = await boxes.count();
let on=[];
for (let i=0;i<n;i++){
  const t=(await boxes.nth(i).innerText()).split('\n')[0];
  const c=await boxes.nth(i).locator('input').isChecked();
  if (c) on.push(t.slice(0,40));
}
console.log('TICKED:', JSON.stringify(on,null,0));
const lbl = p.getByText('Position sizing',{exact:false}).first();
if (await lbl.count()) { await lbl.scrollIntoViewIfNeeded(); await p.waitForTimeout(1200); }
await p.screenshot({path:'/tmp/deploy.png'});
console.log('h-overflow:', await p.evaluate(()=>document.documentElement.scrollWidth-document.documentElement.clientWidth));
await b.close();
