import {chromium} from 'playwright';
const b=await chromium.launch(); const p=await b.newPage({viewport:{width:1440,height:1000}});
// NEVER networkidle: this page polls every 4s so it is never idle
await p.goto('http://localhost:8503/backtest',{waitUntil:'domcontentloaded',timeout:120000});
await p.waitForTimeout(8000);
// textContent, NOT innerText: the label is CSS-uppercased, so innerText yields
// "7 OF 7 CORES WORKING" and a case-sensitive regex on it silently misses.
// And take the DEEPEST match — <html> also "contains" the string.
const info=await p.evaluate(()=>{
  const hits=[...document.querySelectorAll('p,span,div')].filter(e=>/cores? working/i.test(e.textContent||''));
  const el=hits[hits.length-1]; if(!el) return null;
  const panel=el.closest('div.mt-3')||el.parentElement;
  return {line:el.textContent.trim(), panel:panel.innerText};
});
console.log(info? '--- rendered ---\n'+info.panel : '(not found)');
const panel=p.locator('div.mt-3').filter({hasText:/cores? working/i}).first();
await panel.screenshot({path:'cores.png'});
console.log('shot: cores.png');
await b.close();
