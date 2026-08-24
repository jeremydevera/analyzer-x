import {chromium} from 'playwright';
const b=await chromium.launch(); const p=await b.newPage({viewport:{width:1600,height:1300}});
const bad=[], good=new Set();
for (const path of ['/trade','/backtest']) {
  // NEVER networkidle: these pages poll
  await p.goto('http://localhost:8503'+path,{waitUntil:'domcontentloaded',timeout:120000});
  await p.waitForTimeout(9000);
  const t = await p.evaluate(()=>document.body.innerText);
  for (const m of t.matchAll(/[A-Z][a-z]{2} \d{1,2}, \d{4} \d{1,2}:\d{2}[AP]M/g)) bad.push(`${path}: ${m[0]} (uppercase)`);
  for (const m of t.matchAll(/[A-Z][a-z]{2} \d, \d{4}/g)) bad.push(`${path}: ${m[0]} (unpadded day)`);
  for (const m of t.matchAll(/\d{1,2}\/\d{1,2}\/\d{4}/g)) bad.push(`${path}: ${m[0]} (slashes)`);
  for (const m of t.matchAll(/[A-Z][a-z]{2} \d{2}, \d{4} \d{1,2}:\d{2}[ap]m/g)) good.add(`${path}: ${m[0]}`);
}
console.log('WRONG:', bad.length ? [...new Set(bad)].slice(0,6) : 'none');
console.log('correct format on screen:', [...good].slice(0,5));
await b.close();
