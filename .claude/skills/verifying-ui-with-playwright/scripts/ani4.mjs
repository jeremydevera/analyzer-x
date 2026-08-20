import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
const errs=[]; p.on('pageerror',e=>errs.push(String(e).slice(0,110)));
await p.setViewportSize({width:1600,height:1100});
await p.goto('http://localhost:8503', {waitUntil:'domcontentloaded', timeout:120000});
await p.waitForFunction(()=>document.querySelectorAll('.ani').length>0,{timeout:120000});

// 1) the count actually interpolates
const seq=[];
for (let i=0;i<6;i++){
  seq.push(await p.$eval('.mv-hero .v .ani', el =>
    getComputedStyle(el).getPropertyValue('--aw').trim()));
  await p.waitForTimeout(120);
}
console.log('hero --aw over 720ms:', JSON.stringify(seq));

await p.waitForTimeout(2000);
// 2) printed digits == accessible value, for every figure
const r = await p.$$eval('.ani', els => els.map(el => {
  const cs=getComputedStyle(el);
  const aw=parseInt(cs.getPropertyValue('--aw'))||0;
  const af=parseInt(cs.getPropertyValue('--af'))||0;
  const ak=parseInt(cs.getPropertyValue('--ak'))||0;
  const grouped=!!el.querySelector('i.k');
  const vis=el.querySelector('[aria-hidden="true"]');
  const sign=(vis?.textContent||'').trim().startsWith('-')?'-'
            :(vis?.textContent||'').trim().startsWith('+')?'+':'';
  const printed=sign+(grouped?`${ak},${String(aw).padStart(3,'0')}`:`${aw}`)
               +'.'+String(af).padStart(2,'0');
  const sr=(el.querySelector('.ani-sr')?.textContent||'').replace(/\s*USDT\s*$/,'').trim();
  return {printed, sr, ok: printed===sr};
}));
const bad=r.filter(x=>!x.ok);
console.log('figures:', r.length, ' disagreements:', bad.length,
            bad.length?JSON.stringify(bad.slice(0,5)):'(printed digits == accessible value)');
// 3) the sr copy must be invisible but present
const vis = await p.$eval('.ani-sr', el => {
  const cs=getComputedStyle(el); const rc=el.getBoundingClientRect();
  return {display:cs.display, w:Math.round(rc.width), h:Math.round(rc.height)};
});
console.log('ani-sr:', JSON.stringify(vis));
console.log('page errors', errs);
await b.close();
