import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1600,height:1200});
await p.goto('http://localhost:8503', {waitUntil:'networkidle', timeout:120000});
await p.waitForTimeout(10000);
const probe = () => p.evaluate(() => {
  // measure the text width a control must actually display, using canvas with
  // the control's own computed font — not a character-count guess
  const cv = document.createElement('canvas'); const ctx = cv.getContext('2d');
  const textW = (s, cs) => { ctx.font = `${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
                             return ctx.measureText(s).width; };
  const out = [];
  for (const c of document.querySelectorAll('[data-testid="stElementContainer"]')) {
    const w = c.querySelector('[data-testid^="stTextInput"],[data-testid^="stNumberInput"],'
      + '[data-testid^="stSelectbox"],[data-testid^="stMultiSelect"],[data-testid^="stDateInput"]');
    if (!w || w.offsetParent === null) continue;
    const box = w.getBoundingClientRect();
    const inp = w.querySelector('input');
    const cs = getComputedStyle(inp || w);
    const shown = (inp?.value || inp?.placeholder || w.innerText.split('\n').pop() || '').trim();
    const lab = w.querySelector('[data-testid="stWidgetLabel"]')?.innerText?.trim()
             || c.querySelector('[data-testid="stWidgetLabel"]')?.innerText?.trim() || '';
    out.push({label: lab.slice(0,26), kind: w.getAttribute('data-testid'),
              boxW: Math.round(box.width), shown: shown.slice(0,26),
              needW: Math.round(textW(shown, cs))});
  }
  return out;
});
for (const nav of ['Auto Trade','Back Test','Backtest 2','New Crypto','Stocks','LLM Models']) {
  await p.getByText(nav,{exact:true}).first().click();
  await p.waitForTimeout(6500);
  const f = await probe();
  console.log('== ' + nav);
  for (const x of f) {
    const waste = x.boxW - x.needW;
    if (waste > 120) console.log(`   ${String(x.boxW).padStart(4)}px box | needs ${String(x.needW).padStart(4)}px | wastes ${String(waste).padStart(4)}px  ${x.kind.replace('st','')}  "${x.label}"  shows="${x.shown}"`);
  }
}
await b.close();
