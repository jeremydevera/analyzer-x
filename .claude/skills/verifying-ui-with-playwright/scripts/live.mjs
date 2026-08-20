import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1600,height:1100});
// count server pushes: every fragment rerun sends a websocket frame
let frames = 0;
p.on('websocket', ws => ws.on('framereceived', () => frames++));
await p.goto('http://localhost:8503', {waitUntil:'domcontentloaded', timeout:120000});
await p.waitForFunction(()=>/\d{2,3}\.\d\d/.test(document.querySelector('.mv')?.innerText||''),{timeout:120000});
const grab = () => p.evaluate(() => {
  const el = document.querySelector('.mv');
  const t = el?.innerText || '';
  return {pl: (t.match(/[+-]\d+\.\d\d/g)||[]).slice(0,6).join(','),
          pct: (t.match(/\d+%/g)||[]).slice(0,4).join(',')};
});
const t0 = await grab(); const f0 = frames;
console.log('t=0s   ', JSON.stringify(t0), 'frames', f0);
await p.waitForTimeout(20000);
const t1 = await grab();
console.log('t=20s  ', JSON.stringify(t1), 'frames', frames, `(+${frames-f0} pushes)`);
await p.waitForTimeout(18000);
const t2 = await grab();
console.log('t=38s  ', JSON.stringify(t2), 'frames', frames);
console.log(frames - f0 > 0 ? 'REFRESHING: server pushed updates without a reload'
                            : 'STILL FROZEN: no server pushes');
await b.close();
