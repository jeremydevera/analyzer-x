import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
const errs=[]; p.on('pageerror',e=>errs.push(String(e).slice(0,120)));
await p.setViewportSize({width:1500,height:1100});
await p.goto('http://localhost:8503/backtest', {waitUntil:'networkidle', timeout:120000});
await p.waitForTimeout(4000);
const r = await p.evaluate(() => {
  const t = document.body.innerText;
  const grab = (re) => (t.match(re)||[])[0] || null;
  return {
    hasStore: /Backtest store/.test(t),
    hasHistory: /Backtest history/.test(t),
    storeLine: grab(/[\d,]+ measured rows over \d+ pairs? · \d+ coins? · [\d.]+ ?[KMG]?B on this Mac[^\n]*/),
    interruptedWarn: grab(/\d+ pairs? interrupted part-way[^\n]*/),
    historyLine: grab(/\d+ runs? · \d+ ok[^\n]*/),
    outcomes: [...new Set((t.match(/\b(success|failed|crashed)\b/g)||[]))],
    cols: (t.match(/coin\s+tf\s+rows\s+combos\s+size\s+measured through\s+last run/)||[])[0] ? 'all 7' : 'missing',
  };
});
console.log(JSON.stringify(r,null,1));
console.log('page errors:', errs);
const el = await p.$('table');
if (el) { await el.scrollIntoViewIfNeeded(); }
await p.screenshot({path:'btpanels.png', fullPage:false});
await b.close();
