import { chromium } from 'playwright';
const b = await chromium.launch();
const p = await b.newPage({viewport:{width:1500,height:1200}});
const errs=[]; p.on('pageerror',e=>errs.push(String(e)));
await p.goto('http://localhost:8503',{waitUntil:'networkidle'});
await p.waitForTimeout(9000);
await p.getByText('Auto Trade',{exact:true}).first().click();
await p.waitForTimeout(14000);
console.log('JS errors:', errs.length?errs:'none');
const grids = p.locator('[data-testid="stDataFrame"]');
console.log('tables:', await grids.count());
for (let i=0;i<await grids.count();i++){
  const t = await grids.nth(i).innerText();
  console.log(`--- table ${i} ---`);
  console.log(t.split('\n').slice(0,12).join(' | '));
  console.log('  has None:', /\bNone\b/.test(t));
}
const lbl = p.getByText('Positions & PnL — REAL',{exact:false}).first();
await lbl.scrollIntoViewIfNeeded(); await p.waitForTimeout(1500);
await p.screenshot({path:'/tmp/merged2.png'});
console.log('h-overflow:', await p.evaluate(()=>document.documentElement.scrollWidth-document.documentElement.clientWidth));
await b.close();
