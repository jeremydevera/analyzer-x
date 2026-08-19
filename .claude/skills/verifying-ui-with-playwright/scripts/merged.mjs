import { chromium } from 'playwright';
const b = await chromium.launch();
const p = await b.newPage({viewport:{width:1500,height:1200}});
const errs=[]; p.on('pageerror',e=>errs.push(String(e)));
await p.goto('http://localhost:8503',{waitUntil:'networkidle'});
await p.waitForTimeout(9000);
await p.getByText('Auto Trade',{exact:true}).first().click();
await p.waitForTimeout(14000);
console.log('JS errors:', errs.length?errs:'none');
const txt = await p.locator('body').innerText();
console.log('old labels gone:', !/pnl by coin/i.test(txt) && !/open positions —/i.test(txt));
for (const l of ['Positions & PnL — REAL','Positions & PnL — PAPER']) {
  const el = p.getByText(l,{exact:false}).first();
  console.log(l+':', await el.count() ? 'present' : 'MISSING');
}
const grids = p.locator('[data-testid="stDataFrame"]');
console.log('tables in panel:', await grids.count());
const lbl = p.getByText('Positions & PnL — REAL',{exact:false}).first();
if (await lbl.count()) { await lbl.scrollIntoViewIfNeeded(); await p.waitForTimeout(1500); }
await p.screenshot({path:'/tmp/merged.png'});
console.log('h-overflow:', await p.evaluate(()=>document.documentElement.scrollWidth-document.documentElement.clientWidth));
await b.close();
