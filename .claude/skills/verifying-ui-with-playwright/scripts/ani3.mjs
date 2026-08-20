import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1600,height:1100});
await p.goto('http://localhost:8503', {waitUntil:'domcontentloaded', timeout:120000});
await p.waitForFunction(()=>document.querySelectorAll('.ani').length>0,{timeout:120000});
await p.waitForTimeout(2500);

// What each figure SHOULD print, computed from its own animated counters.
const wants = await p.$$eval('.ani', els => els.map(el => {
  const cs = getComputedStyle(el);
  const aw = parseInt(cs.getPropertyValue('--aw'))||0;
  const af = parseInt(cs.getPropertyValue('--af'))||0;
  const ak = parseInt(cs.getPropertyValue('--ak'))||0;
  const grouped = !!el.querySelector('i.k');
  const t = el.textContent.trim();
  const sign = t.startsWith('-') ? '-' : t.startsWith('+') ? '+' : '';
  return sign + (grouped ? `${ak},${String(aw).padStart(3,'0')}` : `${aw}`)
              + '.' + String(af).padStart(2,'0');
}));

// The AX tree includes CSS-generated content in an element's accessible name,
// which is the only way to read ::after counters back out of the page.
const cdp = await p.context().newCDPSession(p);
await cdp.send('Accessibility.enable');
const {nodes} = await cdp.send('Accessibility.getFullAXTree');
const rendered = new Set();
for (const n of nodes) {
  const v = n.name?.value;
  if (typeof v === 'string' && /^[+-]?[\d,]+\.\d\d$/.test(v.trim()))
    rendered.add(v.trim());
}
console.log('figures on page      :', wants.length);
console.log('distinct money strings rendered:', rendered.size);
const missing = [...new Set(wants)].filter(w => !rendered.has(w));
console.log('seeded values NOT rendered:', missing.length,
  missing.length ? JSON.stringify(missing) : '(every figure prints its own value)');
console.log('sample rendered:', JSON.stringify([...rendered].slice(0,14)));
await b.close();
