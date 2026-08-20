import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
const errs=[]; p.on('pageerror',e=>errs.push(String(e).slice(0,120)));
await p.setViewportSize({width:1600,height:1050});
await p.goto('http://localhost:8503', {waitUntil:'domcontentloaded', timeout:120000});
await p.waitForFunction(()=>document.querySelectorAll('.mv-panel').length>0,{timeout:120000});
await p.waitForTimeout(3200);
const r = await p.evaluate(() => {
  const txt = document.body.innerText;
  const risk = document.querySelector('.st-key-tmsec_risk');
  return {
    radioGone: ![...document.querySelectorAll('[data-testid="stRadio"]')]
                  .some(e => /Position sizing/i.test(e.innerText)),
    phraseGone: !/Position sizing/i.test(txt),
    flatWordGone: !/Flat — every trade stakes/i.test(txt),
    riskHeader: risk?.querySelector('h2')?.innerText.replace(/\s+/g,' ').trim(),
    riskWidgets: risk ? risk.querySelectorAll('[data-testid="stElementContainer"]').length : 0,
  };
});
console.log(JSON.stringify(r,null,1));
console.log('page errors', errs);
await b.close();
