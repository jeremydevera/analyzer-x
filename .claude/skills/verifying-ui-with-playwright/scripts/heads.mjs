import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1600,height:1100});
await p.goto('http://localhost:8503', {waitUntil:'domcontentloaded', timeout:120000});
await p.waitForFunction(()=>document.querySelectorAll('.ani').length>0,{timeout:120000});
await p.waitForTimeout(2500);
const r = await p.evaluate(() => {
  const heads = [...document.querySelectorAll('h1,h2,h3,h4,h5,h6')]
    .filter(e=>e.offsetParent).map(e=>({lvl:+e.tagName[1], t:e.innerText.trim().slice(0,40)}));
  // headings faked with divs: the "misuse for styling" the rule names
  const fake = [...document.querySelectorAll('.ta-section,.mv-ph h3,.tm-h')]
    .filter(e=>e.offsetParent).map(e=>({tag:e.tagName, cls:(e.className||'').toString().slice(0,20), t:e.innerText.trim().slice(0,34)}));
  const exp = [...document.querySelectorAll('[data-testid="stExpander"] summary')]
    .map(s=>({label:s.innerText.replace(/\s+/g,' ').trim().slice(0,44), open:!!s.closest('details')?.open}));
  return {heads, fakeCount: fake.length, fake: fake.slice(0,10), exp,
          mainH: (document.querySelector('.stMain')||document.body).scrollHeight};
});
console.log('real headings:', JSON.stringify(r.heads));
console.log('div-as-heading count:', r.fakeCount, JSON.stringify(r.fake));
console.log('expanders:', JSON.stringify(r.exp));
console.log('page height:', r.mainH);
await b.close();
