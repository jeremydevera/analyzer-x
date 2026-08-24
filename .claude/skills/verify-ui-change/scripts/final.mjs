import {chromium} from 'playwright';
const b=await chromium.launch(); const p=await b.newPage({viewport:{width:1500,height:1150}});
const fails=[]; p.on('response',r=>{ if(r.url().includes('/api/')&&r.status()>=400) fails.push(`${r.status()} ${r.url().split('/api/')[1]}`); });
const slow=[]; p.on('requestfinished',async r=>{ try{ const t=r.timing(); if(r.url().includes('/api/')&&t.responseEnd>3000) slow.push(`${(t.responseEnd/1000).toFixed(1)}s ${r.url().split('/api/')[1].slice(0,32)}`);}catch{} });
const errs=[]; p.on('pageerror',e=>errs.push(String(e).slice(0,120)));
// NEVER networkidle: this page polls, so it is never idle
await p.goto('http://localhost:8503/backtest',{waitUntil:'domcontentloaded',timeout:120000});
await p.waitForTimeout(20000);
const t=await p.evaluate(()=>document.body.innerText);
console.log('FAILED /api calls:', fails.length? fails : 'none');
console.log('slower than 3s:', slow.length? slow.slice(0,4) : 'none');
console.log('page errors:', errs.length? errs : 'none');
console.log('api chip:', (t.match(/API (connected|unreachable|on [^\n]*)/)||['(not found)'])[0]);
console.log('count line:', (t.match(/[\d,]+ (?:stored strategies|match)[^\n]*/)||['(none)'])[0]);
console.log('error banner:', (t.match(/HTTP 5\d\d[^\n]*|Error:[^\n]*/)||['none'])[0]);
console.log('cores line:', (t.match(/\d+ OF \d+ CORES WORKING/i)||['(none)'])[0]);
console.log('table rows:', await p.locator('table tbody tr').count());
await p.screenshot({path:'final.png'});
await b.close();
