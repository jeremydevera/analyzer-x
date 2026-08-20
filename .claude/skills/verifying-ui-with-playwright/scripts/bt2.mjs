import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
const errs=[]; p.on('pageerror',e=>errs.push(String(e).slice(0,120)));
await p.setViewportSize({width:1600,height:1050});
await p.goto('http://localhost:8503/?p=backtest-2', {waitUntil:'domcontentloaded', timeout:120000});
await p.waitForFunction(()=>/Backtest 2/.test(document.querySelector('h1')?.innerText||''),{timeout:120000});
await p.waitForTimeout(4000);
const r = await p.evaluate(() => {
  const btn = [...document.querySelectorAll('button')].find(e=>/^DOWNLOAD$/i.test(e.innerText.trim()));
  const cs = btn ? getComputedStyle(btn) : null;
  return {
    downloadPresent: !!btn,
    disabled: btn?.disabled,
    cursor: cs?.cursor,
    tooltip: btn?.getAttribute('title') || btn?.closest('[title]')?.getAttribute('title') || null,
    reasonShown: /Pick at least one coin first/i.test(document.body.innerText),
    runWhereOnPage: /Run where/i.test(document.body.innerText),
    sections: [...document.querySelectorAll('.ta-section, h2.tm-h .k')].map(e=>e.innerText.trim()),
  };
});
console.log(JSON.stringify(r,null,1));
console.log('errors', errs);
await b.close();
