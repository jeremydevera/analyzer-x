import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
const errs=[]; p.on('pageerror',e=>errs.push(String(e).slice(0,110)));
await p.setViewportSize({width:1600,height:1100});
await p.goto('http://localhost:8503', {waitUntil:'domcontentloaded', timeout:120000});
await p.waitForFunction(()=>document.querySelectorAll('.mv').length>0,{timeout:120000});
await p.waitForTimeout(2500);

const probe = () => p.evaluate(() => {
  // Never parse a colour string by hand. The palette is oklch() now, and a
  // regex for rgb() numbers read "oklch(0.09 0.006 265)" as r=0.09 g=0.006
  // b=265 — which produced confident nonsense. Canvas converts ANY CSS colour
  // (oklch, color-mix, named) to sRGB using the browser's own maths.
  const cv = document.createElement('canvas'); cv.width = cv.height = 1;
  const cx = cv.getContext('2d', {willReadFrequently:true});
  const cache = new Map();
  const srgb = (c) => {
    if (cache.has(c)) return cache.get(c);
    cx.clearRect(0,0,1,1); cx.fillStyle = '#000';
    cx.fillStyle = c; cx.fillRect(0,0,1,1);
    const d = cx.getImageData(0,0,1,1).data;
    const v = [d[0], d[1], d[2], d[3]/255];
    cache.set(c, v); return v;
  };
  const lum = (c) => {
    const [r,g,bl] = srgb(c).map(x => x/255)
      .map(x => x <= 0.03928 ? x/12.92 : Math.pow((x+0.055)/1.055, 2.4));
    return 0.2126*r + 0.7152*g + 0.0722*bl;
  };
  const bgOf = (el) => {
    let n = el;
    while (n) {
      const c = getComputedStyle(n).backgroundColor;
      if (c && srgb(c)[3] > 0.05) return c;
      n = n.parentElement;
    }
    return 'rgb(0,0,0)';
  };
  const out = [];
  const seen = new Set();
  for (const el of document.querySelectorAll('p,span,label,div,button,a,b,i,h1,h2,h3,td,th')) {
    if (el.children.length || el.offsetParent === null) continue;
    if (el.classList.contains('ani-sr')) continue;   // 1px accessible copy
    const t = el.innerText?.trim();
    if (!t || t.length > 40 || seen.has(t)) continue;
    const cs = getComputedStyle(el);
    const a = lum(cs.color), z = lum(bgOf(el));
    const ratio = +(((Math.max(a,z)+0.05)/(Math.min(a,z)+0.05))).toFixed(2);
    const px = parseFloat(cs.fontSize);
    const bold = (parseInt(cs.fontWeight)||400) >= 700;
    const large = px >= 24 || (px >= 18.66 && bold);
    const floor = large ? 3.0 : 4.5;
    seen.add(t);
    if (ratio < floor) out.push({t: t.slice(0,30), r: ratio, px, need: floor});
  }
  return out.sort((x,y)=>x.r-y.r);
});
for (const nav of ['Auto Trade','Back Test','Backtest 2','New Crypto','Stocks','LLM Models']) {
  await p.getByText(nav,{exact:true}).first().click();
  await p.waitForTimeout(6500);
  const f = await probe();
  console.log(nav.padEnd(11), f.length ? `${f.length} below floor: ` + JSON.stringify(f.slice(0,8))
                                       : 'all text meets its WCAG floor  PASS');
}
console.log('page errors', errs);
await b.close();
