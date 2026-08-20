import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1600,height:1050});
await p.goto('http://localhost:8503', {waitUntil:'domcontentloaded', timeout:120000});
await p.waitForFunction(()=>document.querySelectorAll('.mv-panel').length>0,{timeout:120000});
await p.waitForTimeout(3000);
const r = await p.evaluate(() => {
  const lbl = [...document.querySelectorAll('label,div,p,span')]
    .find(e => /^ACCOUNT LOSS CAP/i.test((e.innerText||'').trim()));
  if (!lbl) return 'no label';
  const box = lbl.getBoundingClientRect();
  // every small leaf on the same line, to the right of the label's text start
  const hits = [];
  for (const e of document.querySelectorAll('*')) {
    if (e.children.length || e.offsetParent === null) continue;
    const r = e.getBoundingClientRect();
    if (Math.abs(r.top - box.top) > 24) continue;
    if (r.left < box.left) continue;
    if (r.width > 40 || r.width < 3) continue;
    const cs = getComputedStyle(e);
    hits.push({tag:e.tagName, testid:e.getAttribute('data-testid'),
      cls:(e.className||'').toString().slice(0,44),
      txt:JSON.stringify((e.innerText||'').slice(0,6)),
      font:cs.fontFamily.split(',')[0], size:cs.fontSize,
      w:Math.round(r.width), h:Math.round(r.height), left:Math.round(r.left)});
  }
  return {labelLeft:Math.round(box.left), hits};
});
console.log(JSON.stringify(r,null,1));
await b.close();
