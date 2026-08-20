import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1600,height:1050});
await p.goto('http://localhost:8503', {waitUntil:'domcontentloaded', timeout:120000});
await p.waitForFunction(()=>document.querySelectorAll('.mv-panel').length>0,{timeout:120000});
await p.waitForTimeout(3000);
const r = await p.evaluate(() => {
  const txt = document.body.innerText;
  // 1) the close-position control
  const closeSel = [...document.querySelectorAll('[data-testid="stSelectbox"]')]
      .find(e => /close a position/i.test(e.innerText));
  const closeBtn = [...document.querySelectorAll('button')]
      .find(e => /close at market/i.test(e.innerText));
  const openPanel = [...document.querySelectorAll('.mv-panel')]
      .find(e => /open positions/i.test(e.querySelector('h2')?.innerText||''));
  // 2) the two strategy sections and what columns each shows
  const panels = [...document.querySelectorAll('.mv-panel')].map(e=>e.querySelector('h2')?.innerText.trim());
  const stratList = [...document.querySelectorAll('.mv-str .hd span')].map(s=>s.innerText.trim());
  const gridHead = [...document.querySelectorAll('.st-key-tmsec_strategy [data-testid="stHorizontalBlock"]')][0];
  const gridCols = gridHead ? [...gridHead.querySelectorAll('[data-testid="stColumn"]')]
      .map(c=>c.innerText.trim().split('\n')[0]) : [];
  // 3) the risk section
  const risk = document.querySelector('.st-key-tmsec_risk');
  const riskRect = risk ? risk.getBoundingClientRect() : null;
  const riskWidgets = risk ? risk.querySelectorAll('[data-testid="stElementContainer"]').length : 0;
  return {
    closeControl: {
      selectPresent: !!closeSel, buttonPresent: !!closeBtn,
      insideOpenPanel: !!(closeSel && openPanel && openPanel.contains(closeSel)),
      distanceBelowPanel: (closeSel && openPanel)
        ? Math.round(closeSel.getBoundingClientRect().top - openPanel.getBoundingClientRect().bottom) : null,
    },
    panels, stratListCols: stratList, gridCols,
    risk: {h: riskRect?Math.round(riskRect.height):null, widgets: riskWidgets},
    hasBothStrategySections: /Strategies/.test(txt) && /Configure strategies/.test(txt),
  };
});
console.log(JSON.stringify(r,null,1));
await b.close();
