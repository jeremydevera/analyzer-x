import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1600,height:1050});
await p.goto('http://localhost:8503/?p=backtest-2', {waitUntil:'domcontentloaded', timeout:120000});
await p.waitForFunction(()=>document.querySelectorAll('[data-baseweb="select"]').length>0,{timeout:120000});
await p.waitForTimeout(3500);
// TIMEFRAMES already has all 5 chosen -> its menu is the empty state
const sels = await p.$$('[data-baseweb="select"]');
for (let i = 0; i < sels.length; i++) {
  const live = p.locator('[data-baseweb="select"]').nth(i);
  await live.click({timeout:5000}).catch(()=>{});
  await p.waitForTimeout(900);
  const r = await p.evaluate(() => {
    const pop = document.querySelector('[data-baseweb="popover"],[data-baseweb="menu"]');
    if (!pop) return null;
    const txt = pop.innerText.trim().slice(0, 40);
    if (!/no results/i.test(txt)) return {skip: txt.slice(0,20)};
    const cv=document.createElement('canvas'); cv.width=cv.height=1;
    const cx=cv.getContext('2d',{willReadFrequently:true});
    const srgb=c=>{cx.clearRect(0,0,1,1);cx.fillStyle='#000';cx.fillStyle=c;cx.fillRect(0,0,1,1);
      const d=cx.getImageData(0,0,1,1).data;return [d[0],d[1],d[2],d[3]/255];};
    // every element in the empty popover with a light fill
    const out=[];
    const walk=(el,d)=>{ const bg=getComputedStyle(el).backgroundColor;
      const v=srgb(bg);
      if (v[3]>0.05 && v[0]>200 && v[1]>200 && v[2]>200)
        out.push({depth:d, tag:el.tagName,
          bw:el.getAttribute('data-baseweb'), testid:el.getAttribute('data-testid'),
          cls:String(el.className||'').slice(0,30), bg,
          h:Math.round(el.getBoundingClientRect().height)});
      for (const k of el.children) if(d<8) walk(k,d+1); };
    walk(pop,0);
    const leaf=[...pop.querySelectorAll('*')].find(e=>/no results/i.test(e.innerText||'')&&!e.children.length);
    return {text: txt, lightElements: out,
            leafColor: leaf?getComputedStyle(leaf).color:null,
            leafBg: leaf?getComputedStyle(leaf).backgroundColor:null};
  });
  if (r && !r.skip) { console.log('EMPTY-STATE dropdown #' + i); console.log(JSON.stringify(r,null,1)); break; }
  await p.keyboard.press('Escape'); await p.waitForTimeout(300);
}
await b.close();
