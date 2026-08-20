import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1600,height:1050});
await p.goto('http://localhost:8503', {waitUntil:'domcontentloaded', timeout:120000});
await p.waitForFunction(()=>document.querySelectorAll('.mv-panel').length>0,{timeout:120000});
await p.waitForTimeout(3200);
const r = await p.evaluate(() => {
  const sel = [...document.querySelectorAll('[data-testid="stSelectbox"]')]
      .find(e => /close a position/i.test(e.innerText));
  const btn = [...document.querySelectorAll('button')]
      .find(e => /close at market/i.test(e.innerText));
  const openPanel = [...document.querySelectorAll('.mv-panel')]
      .find(e => /open positions/i.test(e.querySelector('h2')?.innerText||''));
  const rows = openPanel ? openPanel.querySelectorAll('.mv-row:not(.hd):not(.ft)').length : 0;
  // is there any per-row close affordance INSIDE the table?
  const inRowBtns = openPanel ? openPanel.querySelectorAll('button, a[role=button]').length : 0;
  return {
    selectPresent: !!sel, buttonPresent: !!btn,
    buttonText: btn?.innerText.trim() || null,
    buttonEnabled: btn ? !btn.disabled : null,
    openRows: rows, perRowButtons: inRowBtns,
    selectValue: sel?.innerText.replace(/\s+/g,' ').trim().slice(0,40) || null,
    yGapBelowTable: (sel && openPanel)
      ? Math.round(sel.getBoundingClientRect().top - openPanel.getBoundingClientRect().bottom)
      : null,
  };
});
console.log(JSON.stringify(r,null,1));
await b.close();
