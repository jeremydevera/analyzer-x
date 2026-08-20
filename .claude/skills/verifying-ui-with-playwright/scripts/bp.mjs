import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
const errs=[]; p.on('pageerror',e=>errs.push(String(e).slice(0,110)));
await p.goto('http://localhost:8503', {waitUntil:'networkidle', timeout:120000});
await p.waitForTimeout(10000);
for (const w of [375,768,1024,1440,1920]) {
  await p.setViewportSize({width:w, height:900});
  await p.waitForTimeout(2500);
  const r = await p.evaluate(() => {
    const main=document.querySelector('.stMain')||document.body;
    const hero=[...document.querySelectorAll('*')].find(e=>/^190\.\d\d$/.test(e.innerText?.trim()||''));
    return {hscroll: main.scrollWidth > main.clientWidth+1,
            docScroll: document.documentElement.scrollWidth > window.innerWidth+1,
            hero: hero?getComputedStyle(hero).fontSize:null};
  });
  console.log(String(w).padStart(5), JSON.stringify(r));
}
console.log('errors', errs);
await b.close();
