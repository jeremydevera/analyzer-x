import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1600,height:1050});
await p.goto('http://localhost:8503/?p=backtest-2', {waitUntil:'domcontentloaded', timeout:120000});
await p.waitForFunction(()=>document.querySelectorAll('[data-baseweb="select"]').length>0,{timeout:120000});
await p.waitForTimeout(3500);
await p.click('[data-baseweb="select"]');
await p.waitForTimeout(1200);
const r = await p.evaluate(() => {
  const pop = document.querySelector('[data-baseweb="popover"]');
  if (!pop) return 'none';
  const out = [];
  const light = c => { const m = c.match(/[\d.]+/g); if (!m) return false;
    // anything whose sRGB is bright
    return c.startsWith('rgb') && (+m[0] > 200 && +m[1] > 200 && +m[2] > 200); };
  const walk = (el, d) => {
    const cs = getComputedStyle(el);
    const bg = cs.backgroundColor;
    if (light(bg)) out.push({depth:d, tag:el.tagName,
      testid:el.getAttribute('data-baseweb') || el.getAttribute('data-testid'),
      cls:String(el.className||'').slice(0,34), role:el.getAttribute('role'),
      bg, h:Math.round(el.getBoundingClientRect().height)});
    for (const k of el.children) if (d < 7) walk(k, d+1);
  };
  walk(pop, 0);
  return out.slice(0, 12);
});
console.log(JSON.stringify(r,null,1));
await b.close();
