import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1600,height:1100});
await p.goto('http://localhost:8503', {waitUntil:'networkidle', timeout:120000});
await p.waitForTimeout(9000);
const r = await p.evaluate(() => {
  const rows = [...document.querySelectorAll('.mv-str > div:not(.hd)')];
  const btns = [...document.querySelectorAll('button')].filter(b=>/1 YEAR/i.test(b.innerText));
  return {
    cleanStrategies: rows.length,
    names: rows.map(r=>r.querySelector('.nm')?.innerText.trim()),
    yearBtnsTotal: btns.length,
    yearBtnsVisible: btns.filter(b=>b.offsetParent!==null).length,
    posRows: document.querySelectorAll('.mv-pos > div:not(.hd)').length,
  };
});
console.log(JSON.stringify(r,null,1));
await b.close();
