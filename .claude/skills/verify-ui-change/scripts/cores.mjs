import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
const errs=[]; p.on('pageerror',e=>errs.push(String(e).slice(0,120)));
await p.setViewportSize({width:1400,height:900});
await p.goto('http://localhost:8503/backtest', {waitUntil:'networkidle', timeout:120000});
await p.waitForTimeout(5000);
const r = await p.evaluate(() => {
  const t = document.body.innerText;
  const line = (t.match(/\d+ of \d+ cores? working/)||[])[0] || null;
  const bars = [...document.querySelectorAll('span')]
    .filter(e => /^#\d+$/.test(e.innerText.trim())).length;
  const pairs = [...t.matchAll(/#(\d+)\s+(\S+ \w+)\s+(\d+%|done)/g)].map(m=>m.slice(1));
  return {coreLine: line, coreRows: bars, samples: pairs.slice(0,8)};
});
console.log(JSON.stringify(r,null,1));
console.log('page errors:', errs);
const jp = await p.$('.mt-3');
if (jp) await jp.screenshot({path:'cores.png'});
await b.close();
