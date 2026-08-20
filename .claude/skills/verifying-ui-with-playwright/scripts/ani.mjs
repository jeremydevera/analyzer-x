import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
const errs=[]; p.on('pageerror',e=>errs.push(String(e).slice(0,110)));
await p.setViewportSize({width:1600,height:1100});
await p.goto('http://localhost:8503', {waitUntil:'domcontentloaded', timeout:120000});
await p.waitForFunction(()=>document.querySelectorAll('.ani').length>0,{timeout:120000});

// 1) is @property actually registered and animating? sample the same figure
//    over time and prove the DIGITS change, not just the CSS being present.
const sample = async () => p.evaluate(() => {
  const el = document.querySelector('.mv-hero .v .ani');
  return {text: el?.innerText.trim(),
          aw: getComputedStyle(el).getPropertyValue('--aw').trim()};
});
const seq = [];
for (let i=0;i<7;i++){ seq.push(await sample()); await p.waitForTimeout(110); }
console.log('hero samples:', JSON.stringify(seq.map(s=>s.text)));
console.log('   --aw     :', JSON.stringify(seq.map(s=>s.aw)));

const info = await p.evaluate(() => {
  const supported = CSS.registerProperty ? true : null;
  const anis = [...document.querySelectorAll('.ani')];
  // does the printed text equal the seeded value? label must match data.
  const bad = [];
  for (const el of anis) {
    const aw = parseInt(getComputedStyle(el).getPropertyValue('--aw'))||0;
    const af = parseInt(getComputedStyle(el).getPropertyValue('--af'))||0;
    const ak = parseInt(getComputedStyle(el).getPropertyValue('--ak'))||0;
    const shown = el.innerText.trim();
    const grouped = !!el.querySelector('i.k');
    const want = (shown.startsWith('-')?'-':shown.startsWith('+')?'+':'')
      + (grouped ? `${ak},${String(aw).padStart(3,'0')}` : `${aw}`)
      + '.' + String(af).padStart(2,'0');
    const norm = shown.replace(/\s*USDT\s*$/,'').trim();
    if (norm !== want) bad.push({shown: norm, want});
  }
  return {count: anis.length, propertySupported: supported, mismatches: bad.slice(0,6)};
});
console.log('animated figures:', info.count, ' @property API:', info.propertySupported);
console.log('text-vs-seed mismatches:', info.mismatches.length,
            info.mismatches.length ? JSON.stringify(info.mismatches) : '(all agree)');
console.log('page errors', errs);
await p.screenshot({path:'ani.png'});
await b.close();
