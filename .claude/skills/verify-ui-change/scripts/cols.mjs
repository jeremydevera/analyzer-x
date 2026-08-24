import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1900,height:1100});
await p.goto('http://localhost:8503/', {waitUntil:'domcontentloaded', timeout:120000});
await p.waitForFunction(()=>document.querySelectorAll('.mv-panel').length>0,{timeout:120000});
await p.waitForTimeout(4000);
const r = await p.evaluate(() => {
  const grid = document.querySelector('.st-key-tmsec_strategy');
  const hdr = grid ? grid.querySelector('[data-testid="stHorizontalBlock"]') : null;
  const gcols = hdr ? [...hdr.querySelectorAll('[data-testid="stColumn"]')]
      .map(c => c.innerText.trim().split('\n')[0]) : [];
  // trade history: find its header row and one data row
  const hist = document.querySelector('.st-key-tmsec_history');
  const hrows = hist ? [...hist.querySelectorAll('[data-testid="stHorizontalBlock"]')].slice(0,3)
      .map(h => [...h.querySelectorAll('[data-testid="stColumn"]')]
          .map(c => c.innerText.trim().replace(/\n/g,'|').slice(0,18))) : [];
  return {gridCols: gcols, histRows: hrows};
});
console.log('STRATEGY GRID:', JSON.stringify(r.gridCols));
console.log('TRADE HISTORY:');
for (const row of r.histRows) console.log('  ', JSON.stringify(row));
await b.close();
