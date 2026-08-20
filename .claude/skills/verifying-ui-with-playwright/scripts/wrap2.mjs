import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
const errs=[]; p.on('pageerror',e=>errs.push(String(e).slice(0,110)));
await p.setViewportSize({width:1600,height:1200});
await p.goto('http://localhost:8503', {waitUntil:'networkidle', timeout:120000});
await p.waitForTimeout(10000);
const probe = () => p.evaluate(() => {
  // A leaf whose text is a single token (no spaces) but renders taller than
  // ~1.6 lines has been broken mid-word. Applies to numbers and labels alike.
  const bad = [];
  for (const el of document.querySelectorAll('p,span,div,button,label')) {
    if (el.children.length || el.offsetParent === null) continue;
    const t = el.innerText?.trim();
    if (!t || /\s/.test(t) || t.length > 24) continue;
    const cs = getComputedStyle(el);
    const lh = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.4;
    if (el.getBoundingClientRect().height > lh * 1.6) bad.push(t);
  }
  const main = document.querySelector('.stMain') || document.body;
  return {brokenTokens: [...new Set(bad)], hscroll: main.scrollWidth > main.clientWidth + 1};
});
for (const nav of ['Auto Trade','Back Test','Backtest 2','New Crypto','Stocks','LLM Models']) {
  await p.getByText(nav, {exact:true}).first().click();
  await p.waitForTimeout(6500);
  const r = await probe();
  console.log(nav.padEnd(11), r.brokenTokens.length ? JSON.stringify(r) : 'no broken tokens, no h-scroll  PASS');
}
console.log('page errors', errs);
await b.close();
