import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
const errs=[]; p.on('pageerror',e=>errs.push(String(e).slice(0,120)));
await p.setViewportSize({width:1600,height:1200});
await p.goto('http://localhost:8503', {waitUntil:'networkidle', timeout:120000});
await p.waitForTimeout(10000);
const probe = () => p.evaluate(() => {
  const lum = (c) => { const m=c.match(/[\d.]+/g).slice(0,3).map(Number)
      .map(v => { v/=255; return v<=0.03928 ? v/12.92 : Math.pow((v+0.055)/1.055,2.4); });
    return 0.2126*m[0] + 0.7152*m[1] + 0.0722*m[2]; };
  const bgOf = (el) => { let n=el; while(n){ const c=getComputedStyle(n).backgroundColor;
      if(c && c!=='rgba(0, 0, 0, 0)') return c; n=n.parentElement; } return 'rgb(0,0,0)'; };
  const out=[]; const seen=new Set();
  for (const el of document.querySelectorAll('p,span,label,div,button,a')) {
    const t = el.innerText?.trim();
    if (!t || t.length>42 || el.children.length || el.offsetParent===null) continue;
    const s=getComputedStyle(el); const a=lum(s.color), z=lum(bgOf(el));
    const r = +(((Math.max(a,z)+0.05)/(Math.min(a,z)+0.05))).toFixed(2);
    if (r < 4.5 && !seen.has(t)) { seen.add(t); out.push({t:t.slice(0,34), r}); }
  }
  return out.sort((a,b)=>a.r-b.r);
});
for (const nav of ['Auto Trade','Back Test','Backtest 2','New Crypto','Stocks','LLM Models']) {
  await p.getByText(nav, {exact:true}).first().click();
  await p.waitForTimeout(7000);
  const f = await probe();
  console.log(nav.padEnd(11), f.length ? JSON.stringify(f) : 'all text >= 4.5:1  PASS');
}
console.log('page errors', errs);
await b.close();
