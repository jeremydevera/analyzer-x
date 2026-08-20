import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1600,height:1100});
await p.goto('http://localhost:8503', {waitUntil:'domcontentloaded', timeout:120000});
await p.waitForFunction(()=>document.querySelectorAll('.ani').length>0,{timeout:120000});
await p.waitForTimeout(2600);
const r = await p.evaluate(() => {
  const rs = getComputedStyle(document.documentElement);
  const norm = s => s.replace(/\s+/g,'');
  const up = norm(rs.getPropertyValue('--buy')) , dn = norm(rs.getPropertyValue('--sell'));
  const hits = [], naked = [];
  for (const el of document.querySelectorAll('*')) {
    if (el.children.length > 2 || el.offsetParent === null) continue;
    const c = norm(getComputedStyle(el).color);
    const t = (el.innerText||'').trim();
    if (!t || t.length > 30) continue;
    const isUp = c === up, isDn = c === dn;
    if (!isUp && !isDn) continue;
    hits.push(t);
    // a non-colour cue: a sign, an arrow, or a word
    const cue = /^[+-]/.test(t) || /[▲▼↑↓]/.test(t) || /[A-Za-z]/.test(t);
    if (!cue) naked.push({t, tone: isUp ? 'up' : 'down'});
  }
  return {coloured: hits.length, naked};
});
console.log('green/red figures:', r.coloured);
console.log('relying on colour ALONE:', r.naked.length,
  r.naked.length ? JSON.stringify(r.naked.slice(0,8)) : '(every one carries a sign or a word)');
await b.close();
