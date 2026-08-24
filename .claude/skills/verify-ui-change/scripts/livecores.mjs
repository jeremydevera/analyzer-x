import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
const errs=[]; p.on('pageerror',e=>errs.push(String(e).slice(0,120)));
await p.setViewportSize({width:1300,height:900});
// NEVER networkidle here: the page polls every 4s so it is never idle
await p.goto('http://localhost:8503/backtest', {waitUntil:'domcontentloaded', timeout:120000});
await p.waitForTimeout(6000);
const read = async () => p.evaluate(() => {
  const t = document.body.innerText;
  return {
    coreLine: (t.match(/\d+ of \d+ cores? working/)||[])[0] || null,
    rows: [...t.matchAll(/#(\d+)\s+(\S+ \w+)\s+(\d+%|done)/g)].map(m=>`#${m[1]} ${m[2]} ${m[3]}`),
  };
});
const a = await read();
console.log('sample 1:', a.coreLine, '\n ', a.rows.join('\n  '));
await p.waitForTimeout(9000);
const c = await read();
console.log('\nsample 2 (9s later):', c.coreLine, '\n ', c.rows.join('\n  '));
const moved = a.rows.filter((r,i) => r !== c.rows[i]).length;
console.log(`\nrows whose percentage CHANGED in 9s: ${moved}`);
console.log('page errors:', errs);
const jp = await p.$('.mt-3');
if (jp) await jp.screenshot({path:'livecores.png'});
await b.close();
