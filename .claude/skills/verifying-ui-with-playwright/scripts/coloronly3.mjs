import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1600,height:1100});
await p.goto('http://localhost:8503', {waitUntil:'domcontentloaded', timeout:120000});
await p.waitForFunction(()=>document.querySelectorAll('.ani').length>0,{timeout:120000});
await p.waitForTimeout(2600);
const r = await p.evaluate(() => {
  const probe = document.createElement('span'); document.body.appendChild(probe);
  const resolve = t => { probe.style.color = `var(${t})`; return getComputedStyle(probe).color; };
  const up = resolve('--buy'), dn = resolve('--sell'); probe.remove();
  const bars = [...document.querySelectorAll('.mv-barrier')];
  const naked = [];
  for (const el of document.querySelectorAll('span,b,div,td,i')) {
    if (el.offsetParent === null) continue;
    const t = (el.innerText||'').trim();
    if (!t || t.length > 30 || /\n/.test(t)) continue;
    const c = getComputedStyle(el).color;
    if (c !== up && c !== dn) continue;
    // The rule is about the information UNIT, not one text node: a cue on a
    // sibling inside the same unit still tells a colourblind reader which way
    // this is going. Judge the nearest unit, then the element itself.
    const unit = el.closest('.mv-barrier, .mv-cell, .mv-row, .tm-h, [data-testid="stColumn"]') || el;
    const ut = (unit.innerText||'').trim();
    const cue = /^[+-]/.test(t) || /[▲▼↑↓]/.test(t) || /[A-Za-z]/.test(t)
              || /[A-Za-z]/.test(ut) || /[▲▼↑↓]/.test(ut);
    if (!cue) naked.push({t, unit: ut.replace(/\s+/g,' ').slice(0,40)});
  }
  return {barriers: bars.length,
          labels: bars.map(e=>e.querySelector('.mv-to')?.innerText.trim()).filter(Boolean),
          naked};
});
console.log('barrier rings:', r.barriers, ' with a named destination:', r.labels.length);
console.log('labels:', JSON.stringify(r.labels));
console.log('colour-alone after the fix:', r.naked.length,
  r.naked.length ? JSON.stringify(r.naked.slice(0,6)) : '(none — every unit names its direction)');
await b.close();
