import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1600,height:1200});
await p.goto('http://localhost:8503', {waitUntil:'networkidle', timeout:120000});
await p.waitForTimeout(10000);
const probe = () => p.evaluate(() => {
  const out = {wrapped: [], clipped: [], hscroll: false};
  for (const el of document.querySelectorAll('button, [data-testid="stPopoverButton"]')) {
    if (el.offsetParent === null) continue;
    const t = el.innerText?.trim(); if (!t) continue;
    const cs = getComputedStyle(el);
    const lh = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize)*1.4;
    // more than one line of text inside a control = a wrapped label
    const inner = el.querySelector('p,span,div') || el;
    if (inner.getBoundingClientRect().height > lh*1.6) out.wrapped.push(t.slice(0,26));
    if (el.scrollWidth > el.clientWidth + 1) out.clipped.push(t.slice(0,26)+' by'+(el.scrollWidth-el.clientWidth)+'px');
  }
  const main = document.querySelector('.stMain') || document.body;
  out.hscroll = main.scrollWidth > main.clientWidth + 1;
  return out;
});
for (const nav of ['Auto Trade','Back Test','Backtest 2','New Crypto','Stocks','LLM Models']) {
  await p.getByText(nav, {exact:true}).first().click();
  await p.waitForTimeout(6500);
  const r = await probe();
  console.log(nav.padEnd(11), JSON.stringify(r));
}
await b.close();
