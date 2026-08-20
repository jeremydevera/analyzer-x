import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1600,height:1200});
await p.goto('http://localhost:8503', {waitUntil:'networkidle', timeout:120000});
await p.waitForTimeout(9000);
await p.getByText('Back Test', {exact:true}).first().click();
await p.waitForTimeout(7000);
const out = await p.evaluate(() => {
  const lum = (c) => { const [r,g,bl] = c.match(/[\d.]+/g).slice(0,3).map(Number)
      .map(v => { v/=255; return v<=0.03928 ? v/12.92 : Math.pow((v+0.055)/1.055,2.4); });
    return 0.2126*r + 0.7152*g + 0.0722*bl; };
  const bgOf = (el) => { let n=el; while(n){ const c=getComputedStyle(n).backgroundColor;
      if(c && c!=='rgba(0, 0, 0, 0)') return c; n=n.parentElement; } return 'rgb(0,0,0)'; };
  const ratio = (el) => { const s=getComputedStyle(el);
    const a=lum(s.color), z=lum(bgOf(el));
    return +(((Math.max(a,z)+0.05)/(Math.min(a,z)+0.05))).toFixed(2); };
  const pick = [];
  for (const el of document.querySelectorAll('p,span,label,div')) {
    const t = el.innerText?.trim();
    if (!t || t.length>42 || el.children.length) continue;
    if (el.offsetParent===null) continue;
    const r = ratio(el);
    if (r < 4.5) pick.push({t: t.slice(0,38), r, color: getComputedStyle(el).color,
                            size: getComputedStyle(el).fontSize});
  }
  const seen=new Set();
  return pick.filter(x=>!seen.has(x.t)&&seen.add(x.t)).sort((a,b)=>a.r-b.r).slice(0,18);
});
console.log(JSON.stringify(out,null,1));
await b.close();
