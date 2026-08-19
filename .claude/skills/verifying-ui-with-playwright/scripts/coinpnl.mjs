import { chromium } from 'playwright';
const b = await chromium.launch();
const p = await b.newPage({viewport:{width:1500,height:1100}});
const errs=[]; p.on('pageerror',e=>errs.push(String(e)));
await p.goto('http://localhost:8503',{waitUntil:'networkidle'});
await p.waitForTimeout(9000);
const tab = p.locator('[data-testid="stButton"] button').filter({hasText:/^Auto Trade$/});
if (await tab.count()) { await tab.first().click(); }
else { await p.getByText('Auto Trade',{exact:true}).first().click(); }
await p.waitForTimeout(12000);
console.log('JS errors:', errs.length?errs:'none');
const txt = await p.locator('body').innerText();
console.log('on Auto Trade tab:', /auto trade/i.test(txt));
for (const lbl of ['PnL by coin — REAL (money)','PnL by coin — PAPER (demo)']) {
  const el = p.getByText(lbl, {exact:false}).first();
  const found = await el.count();
  let bb = null; if (found) { try { bb = await el.boundingBox(); } catch {} }
  console.log(`${lbl}:`, found ? (bb?`x=${Math.round(bb.x)} y=${Math.round(bb.y)}`:'found, no box') : 'NOT FOUND');
}
const grids = p.locator('[data-testid="stDataFrame"]');
const n = await grids.count();
console.log('dataframes:', n);
for (let i=0;i<n;i++) console.log(`  df[${i}]:`, (await grids.nth(i).innerText()).replace(/\n/g,' | ').slice(0,300));
const lbl = p.getByText('PnL by coin — REAL (money)', {exact:false}).first();
if (await lbl.count()) { await lbl.scrollIntoViewIfNeeded(); await p.waitForTimeout(1500); }
await p.screenshot({path:'/tmp/coinpnl.png'});
await p.screenshot({path:'/tmp/coinpnl-full.png', fullPage:true});
console.log('h-overflow:', await p.evaluate(()=>document.documentElement.scrollWidth-document.documentElement.clientWidth));
await b.close();
