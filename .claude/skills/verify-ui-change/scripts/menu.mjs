import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1600,height:1050});
await p.goto('http://localhost:8503/?p=backtest-2', {waitUntil:'domcontentloaded', timeout:120000});
await p.waitForFunction(()=>document.querySelectorAll('[data-baseweb="select"]').length>0,{timeout:120000});
await p.waitForTimeout(3500);
// open the TIMEFRAMES multiselect
await p.click('[data-testid="stMultiSelect"]:nth-of-type(1) [data-baseweb="select"]').catch(async()=>{
  await p.click('[data-baseweb="select"]');
});
await p.waitForTimeout(1200);
const r = await p.evaluate(() => {
  const cv=document.createElement('canvas'); cv.width=cv.height=1;
  const cx=cv.getContext('2d',{willReadFrequently:true});
  const srgb=c=>{cx.clearRect(0,0,1,1);cx.fillStyle='#000';cx.fillStyle=c;cx.fillRect(0,0,1,1);
    const d=cx.getImageData(0,0,1,1).data;return [d[0],d[1],d[2],d[3]/255];};
  const lum=c=>{const [r,g,bl]=srgb(c).map(x=>x/255)
    .map(x=>x<=0.03928?x/12.92:Math.pow((x+0.055)/1.055,2.4));
    return 0.2126*r+0.7152*g+0.0722*bl;};
  const pop = document.querySelector('[data-baseweb="popover"], [data-baseweb="menu"]');
  if (!pop) return 'no popover open';
  const inApp = !!pop.closest('.stApp');
  const cs = getComputedStyle(pop);
  const inner = pop.querySelector('ul,li,div');
  const ics = inner ? getComputedStyle(inner) : null;
  const txt = [...pop.querySelectorAll('li,div,span')]
    .filter(e=>e.children.length===0 && e.innerText?.trim())
    .slice(0,3).map(e=>({t:e.innerText.trim().slice(0,22),
      color:getComputedStyle(e).color,
      ratio:+(((Math.max(lum(getComputedStyle(e).color),lum(cs.backgroundColor))+0.05)/
               (Math.min(lum(getComputedStyle(e).color),lum(cs.backgroundColor))+0.05))).toFixed(2)}));
  return {portaled: !inApp, parent: pop.parentElement?.tagName,
          popBg: cs.backgroundColor, popText: cs.color,
          innerBg: ics?.backgroundColor, items: txt};
});
console.log(JSON.stringify(r,null,1));
await p.screenshot({path:'menu_open.png'});
await b.close();
