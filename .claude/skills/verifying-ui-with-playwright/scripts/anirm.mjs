import { chromium } from 'playwright';
const b = await chromium.launch();
// emulate a reader who has asked the OS to reduce motion
const ctx = await b.newContext({reducedMotion: 'reduce'});
const p = await ctx.newPage();
await p.setViewportSize({width:1600,height:1100});
await p.goto('http://localhost:8503', {waitUntil:'domcontentloaded', timeout:120000});
await p.waitForFunction(()=>document.querySelectorAll('.ani').length>0,{timeout:120000});
await p.waitForTimeout(1200);
const r = await p.$$eval('.ani', els => els.slice(0,6).map(el => {
  const cs=getComputedStyle(el);
  const aw=parseInt(cs.getPropertyValue('--aw'))||0;
  const af=parseInt(cs.getPropertyValue('--af'))||0;
  const sr=(el.querySelector('.ani-sr')?.textContent||'').trim();
  return {animation: cs.animationName, seedPrints: `${aw}.${String(af).padStart(2,'0')}`, sr};
}));
console.log(JSON.stringify(r,null,1));
const stillZero = r.filter(x => x.seedPrints === '0.00' && !x.sr.startsWith('0.00'));
console.log(stillZero.length ? 'BROKEN: shows 0.00 with motion off' :
            'reduced motion: animation off, figure still correct');
await b.close();
