import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1600,height:1100});
await p.goto('http://localhost:8503', {waitUntil:'domcontentloaded', timeout:120000});
await p.waitForFunction(()=>document.querySelectorAll('.ani').length>0,{timeout:120000});
await p.waitForTimeout(2600);
const r = await p.evaluate(() => {
  // Resolve each token THROUGH the browser so both sides are the same
  // notation. Comparing a computed rgb() to a raw oklch() token found zero
  // matches and looked like a pass.
  const probe = document.createElement('span');
  document.body.appendChild(probe);
  const resolve = tok => { probe.style.color = `var(${tok})`;
                           return getComputedStyle(probe).color; };
  const up = resolve('--buy'), dn = resolve('--sell');
  probe.remove();
  const naked = [], hits = [];
  for (const el of document.querySelectorAll('span,b,div,td,i')) {
    if (el.offsetParent === null) continue;
    const t = (el.innerText||'').trim();
    if (!t || t.length > 30 || /\n/.test(t)) continue;
    const c = getComputedStyle(el).color;
    if (c !== up && c !== dn) continue;
    hits.push(t);
    const cue = /^[+-]/.test(t) || /[▲▼↑↓]/.test(t) || /[A-Za-z]/.test(t);
    if (!cue) naked.push({t, tone: c === up ? 'up' : 'down'});
  }
  return {up, dn, coloured: hits.length, sample: [...new Set(hits)].slice(0,10), naked};
});
console.log('--buy resolves to', r.up, ' --sell', r.dn);
console.log('green/red figures found:', r.coloured, JSON.stringify(r.sample));
console.log('relying on colour ALONE:', r.naked.length,
  r.naked.length ? JSON.stringify(r.naked.slice(0,8)) : '(all carry a sign or a word)');
await b.close();
