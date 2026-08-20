import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1600,height:1100});
await p.goto('http://localhost:8503', {waitUntil:'domcontentloaded', timeout:120000});
await p.waitForFunction(()=>document.querySelectorAll('.ani').length>0,{timeout:120000});
await p.waitForTimeout(3000);
const r = await p.evaluate(() => {
  const sr = el => el?.querySelector('.ani-sr')?.textContent.trim() || null;
  const out = {};
  // the OPEN NOW tile: headline vs its own itemised caption
  const cells = [...document.querySelectorAll('.mv-cell')];
  const tile = cells.find(c => /open now/i.test(c.innerText));
  if (tile) {
    out.headline = sr(tile.querySelector('.ani'));
    const cap = tile.querySelector('span:last-child')?.textContent || '';
    const parts = [...cap.matchAll(/([+-]\d+\.\d\d)/g)].map(m=>parseFloat(m[1]));
    out.caption = cap.trim();
    out.partsSum = parts.length ? parts.reduce((a,v)=>a+v,0).toFixed(2) : null;
  }
  // each positions table: rows vs footer
  out.tables = [...document.querySelectorAll('.mv-panel')].map(panel => {
    const h = panel.querySelector('h2')?.innerText.trim();
    const rows = [...panel.querySelectorAll('.mv-row:not(.hd):not(.ft)')];
    const ft = panel.querySelector('.mv-row.ft');
    if (!ft || !rows.length) return null;
    const rowPl = rows.map(r => parseFloat(sr(r.querySelectorAll('.ani')[0])||'0'));
    const rowRisk = rows.map(r => parseFloat(sr(r.querySelectorAll('.ani')[1])||'0'));
    const fa = ft.querySelectorAll('.ani');
    return {h, rows: rows.length,
      plSum: rowPl.reduce((a,v)=>a+v,0).toFixed(2), plFooter: sr(fa[0]),
      riskSum: rowRisk.reduce((a,v)=>a+v,0).toFixed(2), riskFooter: sr(fa[1])};
  }).filter(Boolean);
  return out;
});
console.log('OPEN NOW headline:', r.headline, '| caption:', r.caption, '| parts sum:', r.partsSum,
            r.headline && r.partsSum && parseFloat(r.headline).toFixed(2)===r.partsSum ? 'AGREE' : 'DISAGREE');
for (const t of r.tables)
  console.log(`${t.h}: rows ${t.rows} | P/L ${t.plSum} vs footer ${t.plFooter} ` +
    `${parseFloat(t.plFooter).toFixed(2)===t.plSum?'AGREE':'DISAGREE'}` +
    ` | risk ${t.riskSum} vs ${t.riskFooter} ${parseFloat(t.riskFooter).toFixed(2)===t.riskSum?'AGREE':'DISAGREE'}`);
await b.close();
