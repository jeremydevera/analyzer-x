import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
const errs=[]; p.on('pageerror',e=>errs.push(String(e).slice(0,110)));
await p.setViewportSize({width:1600,height:1100});
await p.goto('http://localhost:8503', {waitUntil:'domcontentloaded', timeout:120000});
await p.waitForFunction(()=>document.querySelectorAll('.ani').length>0,{timeout:120000});
await p.waitForTimeout(2500);   // let the count finish

// innerText cannot see ::after content. The accessibility tree CAN: generated
// content is part of an element's accessible name. That is how the rendered
// DIGITS get read back, rather than the seed values that produced them.
const snap = await p.accessibility.snapshot({interestingOnly:false});
const names = [];
(function walk(n){ if(!n) return; if(n.name) names.push(n.name.trim());
                   (n.children||[]).forEach(walk); })(snap);
const moneyLike = names.filter(t => /^[+-]?[\d,]+\.\d\d(\s*USDT)?$/.test(t));
console.log('money strings read from the a11y tree:', moneyLike.length);
console.log(JSON.stringify(moneyLike.slice(0,16)));

const check = await p.evaluate(() => {
  const out = {mismatch: [], n: 0};
  for (const el of document.querySelectorAll('.ani')) {
    const cs = getComputedStyle(el);
    const aw = parseInt(cs.getPropertyValue('--aw'))||0;
    const af = parseInt(cs.getPropertyValue('--af'))||0;
    const ak = parseInt(cs.getPropertyValue('--ak'))||0;
    const grouped = !!el.querySelector('i.k');
    const sign = el.textContent.trim().startsWith('-') ? '-'
               : el.textContent.trim().startsWith('+') ? '+' : '';
    const want = sign + (grouped ? `${ak},${String(aw).padStart(3,'0')}` : `${aw}`)
                      + '.' + String(af).padStart(2,'0');
    out.n++;
    // the a11y name is what the reader actually gets
    if (!el.getAttribute('data-x')) el.setAttribute('data-want', want);
  }
  return out;
});
const wants = await p.$$eval('.ani', els => els.map(e => e.getAttribute('data-want')));
const missing = wants.filter(w => !moneyLike.some(m => m.replace(/\s*USDT/,'') === w));
console.log('figures on page:', check.n);
console.log('seeded values NOT found in the rendered a11y text:', missing.length,
            missing.length ? JSON.stringify(missing) : '(every figure renders its own value)');
console.log('page errors', errs);
await b.close();
