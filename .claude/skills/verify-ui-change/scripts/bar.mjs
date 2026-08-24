import {chromium} from 'playwright';
const b=await chromium.launch(); const p=await b.newPage({viewport:{width:1600,height:1200}});
// NEVER networkidle: the page polls
await p.goto('http://localhost:8503/backtest',{waitUntil:'domcontentloaded',timeout:120000});
await p.waitForTimeout(9000);
const t=await p.evaluate(()=>document.body.innerText);
console.log('progress line:', (t.match(/full grid[^\n]*/)||['(none)'])[0].slice(0,110));
console.log('counter:      ', (t.match(/\d{1,4}\/\d{3,4}/g)||['(none)']).slice(0,3).join('  '));
console.log('cores:        ', (t.match(/\d+ OF \d+ CORES WORKING/i)||['(none)'])[0]);
await p.screenshot({path:'bar.png',clip:{x:300,y:330,width:1250,height:230}});
await b.close();
