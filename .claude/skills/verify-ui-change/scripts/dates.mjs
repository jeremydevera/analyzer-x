import {chromium} from 'playwright';
const b=await chromium.launch(); const p=await b.newPage({viewport:{width:1500,height:1200}});
const bad=[], good=new Set();
for (const path of ['/trade','/backtest','/new-crypto']) {
  // NEVER networkidle: these pages poll
  await p.goto('http://localhost:8503'+path,{waitUntil:'domcontentloaded',timeout:120000});
  await p.waitForTimeout(7000);
  const t = await p.evaluate(()=>document.body.innerText);
  for (const m of t.matchAll(/\b\d{1,2}\/\d{1,2}\/\d{4}[^\n]{0,14}/g)) bad.push(`${path}: ${m[0].trim()}`);
  for (const m of t.matchAll(/[A-Z][a-z]{2} \d{1,2}, \d{4} \d{1,2}:\d{2}[AP]M/g)) good.add(`${path}: ${m[0]}`);
  for (const m of t.matchAll(/[A-Z][a-z]{2} \d{1,2}, \d{1,2}:\d{2} [AP]M/g)) bad.push(`${path}: ${m[0]} (no year, spaced AM)`);
}
console.log('WRONG format on screen:', bad.length ? bad.slice(0,6) : 'none');
console.log('operator format seen:', [...good].slice(0,6));
await b.close();
