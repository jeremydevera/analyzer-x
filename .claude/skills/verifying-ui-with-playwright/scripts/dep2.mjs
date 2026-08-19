import { chromium } from 'playwright';
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1900, height: 1400 } });
await p.goto('file:///Users/jeremydevera/Desktop/Trading%20Agents/reports/15m30m-year-5coins.html',{waitUntil:'load'});
await p.waitForTimeout(10000);
const info = await p.evaluate(()=>{
  const el=document.getElementById('recbox');
  return {exists: !!el, htmlLen: el?el.innerHTML.length:0,
          text: el?el.innerText.slice(0,220):'',
          hasLive: el?el.innerHTML.includes('Live right now'):false,
          visible: el?(el.offsetParent!==null):false,
          display: el?getComputedStyle(el).display:'-'};
});
console.log(JSON.stringify(info,null,1));
