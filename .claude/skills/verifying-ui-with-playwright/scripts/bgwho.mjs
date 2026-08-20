import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1600,height:1100});
await p.goto('http://localhost:8503', {waitUntil:'domcontentloaded', timeout:120000});
await p.waitForFunction(()=>document.querySelectorAll('.mv').length>0,{timeout:120000});
await p.waitForTimeout(2500);
const r = await p.evaluate(() => {
  const cv=document.createElement('canvas'); cv.width=cv.height=1;
  const cx=cv.getContext('2d',{willReadFrequently:true});
  const srgb=c=>{cx.clearRect(0,0,1,1);cx.fillStyle='#000';cx.fillStyle=c;cx.fillRect(0,0,1,1);
                 const d=cx.getImageData(0,0,1,1).data;return [d[0],d[1],d[2],d[3]/255];};
  const want=['Save & run','Auto Trade'];
  const out=[];
  for (const el of document.querySelectorAll('*')) {
    if (el.children.length || el.offsetParent===null) continue;
    const t=(el.innerText||'').trim();
    if (!want.includes(t)) continue;
    let n=el, hops=0, src=null;
    while(n){ const c=getComputedStyle(n).backgroundColor;
      if (c && srgb(c)[3] > 0.05){ src={tag:n.tagName, testid:n.getAttribute?.('data-testid'),
        cls:(n.className||'').toString().slice(0,38), bg:c, hops}; break; }
      n=n.parentElement; hops++; }
    out.push({t, color:getComputedStyle(el).color, bgFrom:src});
  }
  return out;
});
for (const x of r) console.log('##', x.t, '\n   ink', x.color, '\n   bg  ', JSON.stringify(x.bgFrom));
await b.close();
