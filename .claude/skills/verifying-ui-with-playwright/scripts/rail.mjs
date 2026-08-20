import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
const errs=[]; p.on('pageerror',e=>errs.push(String(e).slice(0,110)));
await p.setViewportSize({width:1600,height:1050});
await p.goto('http://localhost:8503', {waitUntil:'domcontentloaded', timeout:120000});
await p.waitForFunction(()=>document.querySelectorAll('.nvx-i').length>0,{timeout:120000});
await p.waitForTimeout(1500);
const r = await p.evaluate(() => {
  const rail = document.querySelector('[data-testid="stSidebar"]');
  const items = [...document.querySelectorAll('.nvx-i')];
  return {
    railW: Math.round(rail.getBoundingClientRect().width),
    stButtonsInRail: rail.querySelectorAll('button[data-testid^="stBaseButton"]').length,
    items: items.map(a => ({t:a.querySelector('.nvx-l')?.innerText,
      h: Math.round(a.getBoundingClientRect().height),
      icon: !!a.querySelector('svg'),
      badge: a.querySelector('.nvx-b')?.innerText || null,
      on: a.classList.contains('on')})),
    gap: items.length>1 ? Math.round(items[1].getBoundingClientRect().top
                                   - items[0].getBoundingClientRect().bottom) : null,
    navHeight: Math.round(document.querySelector('.nvx').getBoundingClientRect().height),
  };
});
console.log('rail width', r.railW, '| st.buttons left in rail:', r.stButtonsInRail);
console.log('row gap', r.gap, '| whole nav height', r.navHeight);
for (const i of r.items) console.log('  ', String(i.h)+'px', i.icon?'icon':'NO-ICON',
  (i.badge?('badge '+i.badge):'      ').padEnd(9), i.on?'ACTIVE':'', i.t);
console.log('errors', errs);
await b.close();
