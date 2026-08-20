import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1600,height:1050});
await p.goto('http://localhost:8503/?p=backtest-2', {waitUntil:'domcontentloaded', timeout:120000});
await p.waitForFunction(()=>/Backtest 2/.test(document.querySelector('h1')?.innerText||''),{timeout:120000});
await p.waitForTimeout(4000);
const r = await p.evaluate(() => {
  const out = [];
  for (const ms of document.querySelectorAll('[data-testid="stMultiSelect"],[data-testid="stSelectbox"]')) {
    if (ms.offsetParent === null) continue;
    const inp = ms.querySelector('input');
    if (!inp) continue;
    const cs = getComputedStyle(inp);
    const r = inp.getBoundingClientRect();
    out.push({
      widget: ms.getAttribute('data-testid'),
      label: ms.querySelector('[data-testid="stWidgetLabel"]')?.innerText.trim().slice(0,14),
      innerInput: {w:Math.round(r.width), h:Math.round(r.height),
        border:cs.borderTopWidth+' '+cs.borderTopColor,
        radius:cs.borderTopLeftRadius, bg:cs.backgroundColor,
        minH:cs.minHeight, shadow:cs.boxShadow.slice(0,40)},
    });
  }
  return out.slice(0,4);
});
console.log(JSON.stringify(r,null,1));
await b.close();
