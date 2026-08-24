import {chromium} from 'playwright';
const b=await chromium.launch(); const p=await b.newPage({viewport:{width:1500,height:1100}});
const fails=[]; p.on('response',r=>{ if(r.url().includes('/api/') && r.status()>=400) fails.push(`${r.status()} ${r.url().split('/api/')[1]}`); });
const errs=[]; p.on('pageerror',e=>errs.push(String(e).slice(0,140)));
const t0=Date.now();
// NEVER networkidle: this page polls, so it is never idle
await p.goto('http://localhost:8503/backtest',{waitUntil:'domcontentloaded',timeout:120000});
await p.waitForTimeout(12000);
console.log(`load+settle: ${((Date.now()-t0)/1000).toFixed(1)}s`);
console.log('FAILED /api calls:', fails.length? fails : 'none');
console.log('page errors:', errs.length? errs : 'none');
const txt=await p.evaluate(()=>document.body.innerText);
const m=txt.match(/[\d,]+ (?:stored strategies|match)[^\n]*/);
console.log('count line:', m? m[0] : '(not found)');
const idx=txt.match(/indexing [^\n]*/i); console.log('index note:', idx? idx[0] : '(none — index is current)');
const err=txt.match(/HTTP 5\d\d[^\n]*|Error:[^\n]*/); console.log('error banner:', err? err[0] : 'none');
const rows=await p.locator('table tbody tr').count(); console.log('strategy table rows:', rows);
await p.screenshot({path:'strat.png',fullPage:false});
await b.close();
