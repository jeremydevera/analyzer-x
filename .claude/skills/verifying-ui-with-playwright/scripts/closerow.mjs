import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
const errs=[]; p.on('pageerror',e=>errs.push(String(e).slice(0,120)));
await p.setViewportSize({width:1600,height:1050});
await p.goto('http://localhost:8503', {waitUntil:'domcontentloaded', timeout:120000});
await p.waitForFunction(()=>document.querySelectorAll('.mv-panel').length>0,{timeout:120000});
await p.waitForTimeout(3200);
const before = await p.evaluate(() => {
  const live = [...document.querySelectorAll('.mv-panel')]
    .find(e=>/open positions/i.test(e.querySelector('h2')?.innerText||''));
  const paper = [...document.querySelectorAll('.mv-panel')]
    .find(e=>/demo positions/i.test(e.querySelector('h2')?.innerText||''));
  return {
    liveRows: live.querySelectorAll('.mv-row:not(.hd):not(.ft)').length,
    liveXs: live.querySelectorAll('.mv-x').length,
    paperXs: paper.querySelectorAll('.mv-x').length,
    header: [...live.querySelectorAll('.mv-row.hd > div')].map(d=>d.innerText.trim()),
    dropdownGone: ![...document.querySelectorAll('[data-testid="stSelectbox"]')]
        .some(e=>/close a position/i.test(e.innerText)),
    confirmShowing: /Close .* at market now\?/.test(document.body.innerText),
  };
});
console.log('before click:', JSON.stringify(before));
// ARM only — click the row's x. This must NOT send an order.
await p.click('.mv-panel .mv-x');
await p.waitForTimeout(4000);
const after = await p.evaluate(() => {
  const t = document.body.innerText;
  const warn = document.querySelector('[data-testid="stAlertContainer"], .stAlert');
  const live = [...document.querySelectorAll('.mv-panel')]
    .find(e=>/open positions/i.test(e.querySelector('h2')?.innerText||''));
  const conf = [...document.querySelectorAll('button')].find(e=>/CONFIRM/i.test(e.innerText));
  return {
    confirmVisible: !!conf,
    confirmY: conf ? Math.round(conf.getBoundingClientRect().top) : null,
    tableBottom: Math.round(live.getBoundingClientRect().bottom),
    askedAtMarket: /at market now\?/.test(t),
    namesUnrealised: /becomes real the moment/.test(t),
    url: location.search,
  };
});
console.log('after arming :', JSON.stringify(after));
console.log('gap confirm-below-table:', after.confirmY!==null ? after.confirmY-after.tableBottom : null);
console.log('errors', errs);
await p.screenshot({path:'close_row.png'});
await b.close();
