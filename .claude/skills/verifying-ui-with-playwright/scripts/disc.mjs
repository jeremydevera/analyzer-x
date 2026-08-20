import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
const errs=[]; p.on('pageerror',e=>errs.push(String(e).slice(0,120)));
await p.setViewportSize({width:1600,height:1100});
await p.goto('http://localhost:8503', {waitUntil:'networkidle', timeout:120000});
await p.waitForTimeout(9000);
const st = await p.evaluate(() => {
  const exps = [...document.querySelectorAll('[data-testid="stExpander"] summary')]
    .map(s => ({label: s.innerText.replace(/\s+/g,' ').trim().slice(0,60),
                open: !!s.closest('details')?.open}));
  const txt = document.body.innerText;
  const count = (re) => (txt.match(re)||[]).length;
  return {
    exps,
    pageH: document.documentElement.scrollHeight,
    // "trend50" appears once per strategy render; the clean list is one,
    // the old control grid another. Two means the duplication is back.
    trend50: count(/trend50/gi),
    ladderCaption: /is the whole DEEP sequence/.test(txt),
    viewRows: document.querySelectorAll('.mv-row').length,
  };
});
console.log(JSON.stringify(st,null,1)); console.log('errors', errs);
await p.screenshot({path:'disc.png', fullPage:true});
await b.close();
