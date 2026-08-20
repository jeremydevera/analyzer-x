import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
const errs=[]; p.on('pageerror',e=>errs.push(String(e).slice(0,120)));
await p.setViewportSize({width:1600,height:1100});
await p.goto('http://localhost:8503', {waitUntil:'networkidle', timeout:120000});
await p.waitForTimeout(9000);

const closed = await p.evaluate(() => {
  const main = document.querySelector('.stMain') || document.querySelector('section.main');
  // Count the CLEAN list's rows from the DOM, not from rendered text.
  const strat = [...document.querySelectorAll('.mv-sname')].map(e=>e.innerText.trim());
  return {scrollH: main?.scrollHeight, viewport: window.innerHeight,
          cleanStrategies: strat.length, names: strat};
});
console.log('collapsed', JSON.stringify(closed));

// Open "Configure strategies" and prove the control grid is intact underneath.
await p.getByText(/Configure strategies/).click();
await p.waitForTimeout(6000);
const open = await p.evaluate(() => {
  const txt = document.body.innerText;
  return {
    ladderCaption: /is the whole DEEP sequence/.test(txt),
    // the grid prints each strategy again; checkboxes and the 1 YEAR buttons
    // are the controls that only exist in the grid
    checkboxes: document.querySelectorAll('[data-testid="stCheckbox"]').length,
    yearBtns: [...document.querySelectorAll('button')].filter(b=>/1 YEAR/i.test(b.innerText)).length,
    baseInputs: [...document.querySelectorAll('input')].filter(i=>i.getAttribute('aria-label')?.match(/base/i)).length,
    gridTrend50: (txt.match(/trend50/gi)||[]).length,
  };
});
console.log('opened   ', JSON.stringify(open));
console.log('errors', errs);
await p.screenshot({path:'disc_open.png'});
await b.close();
