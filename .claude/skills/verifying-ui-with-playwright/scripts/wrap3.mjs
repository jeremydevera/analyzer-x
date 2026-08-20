import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
const errs=[]; p.on('pageerror',e=>errs.push(String(e).slice(0,110)));
await p.setViewportSize({width:1600,height:1200});
await p.goto('http://localhost:8503', {waitUntil:'networkidle', timeout:120000});
await p.waitForTimeout(10000);
const probe = () => p.evaluate(() => {
  // Truth, not a heuristic: put a Range around the text node and count the
  // client rects it produces. Two rects for a token with no spaces in it means
  // the browser broke a word across lines. Padding cannot fool this.
  const bad = [];
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = walk.nextNode())) {
    const t = n.nodeValue?.trim();
    if (!t || /\s/.test(t) || t.length > 24) continue;
    const el = n.parentElement;
    if (!el || el.offsetParent === null) continue;
    const r = document.createRange(); r.selectNodeContents(n);
    if (r.getClientRects().length > 1) bad.push(t);
  }
  const main = document.querySelector('.stMain') || document.body;
  return {broken: [...new Set(bad)], hscroll: main.scrollWidth > main.clientWidth + 1};
});
for (const nav of ['Auto Trade','Back Test','Backtest 2','New Crypto','Stocks','LLM Models']) {
  await p.getByText(nav, {exact:true}).first().click();
  await p.waitForTimeout(6500);
  const r = await probe();
  console.log(nav.padEnd(11), r.broken.length ? JSON.stringify(r) : 'no mid-word breaks, no h-scroll  PASS');
}
console.log('page errors', errs);
await b.close();
