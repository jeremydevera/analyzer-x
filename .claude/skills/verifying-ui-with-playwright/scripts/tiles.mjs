import { chromium } from 'playwright';
const b = await chromium.launch();
const p = await b.newPage({viewport:{width:1500,height:1200}});
const errs=[]; p.on('pageerror',e=>errs.push(String(e)));
await p.goto('http://localhost:8503',{waitUntil:'networkidle'});
await p.waitForTimeout(9000);
await p.getByText('Auto Trade',{exact:true}).first().click();
await p.waitForTimeout(14000);
console.log('JS errors:', errs.length?errs:'none');
for (const t of ['Momentum 15 (1h) · TP 2.4% — GOLD','Momentum 6 (1h) · TP 2.0% — PAXG']) {
  const el = p.getByText(t,{exact:false}).first();
  const ok = await el.count();
  console.log(t.slice(0,34)+':', ok ? 'PRESENT' : 'MISSING');
  if (ok) { const bb=await el.boundingBox(); console.log('   at y='+Math.round(bb.y)); }
}
const gold = p.getByText('Momentum 15 (1h) · TP 2.4% — GOLD',{exact:false}).first();
if (await gold.count()) { await gold.scrollIntoViewIfNeeded(); await p.waitForTimeout(1500); }
await p.screenshot({path:'/tmp/tiles.png'});
console.log('h-overflow:', await p.evaluate(()=>document.documentElement.scrollWidth-document.documentElement.clientWidth));
await b.close();
