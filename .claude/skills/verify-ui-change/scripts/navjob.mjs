import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
const errs=[]; p.on('pageerror',e=>errs.push(String(e).slice(0,120)));
await p.setViewportSize({width:1600,height:950});
const chip = async (where) => {
  await p.waitForTimeout(5000);            // let the 4s poll land
  const r = await p.evaluate(() => {
    const a = [...document.querySelectorAll('a')]
      .find(x => /backtesting|downloading|updating/i.test(x.innerText));
    return a ? {text: a.innerText.replace(/\s+/g,' ').trim(),
                spinner: !!a.querySelector('svg.animate-spin'),
                href: a.getAttribute('href')} : null;
  });
  console.log(`${where.padEnd(22)} ${r ? 'CHIP: ' + JSON.stringify(r) : 'no chip'}`);
  return r;
};
// start on the backtest screen, then navigate away twice
await p.goto('http://localhost:8503/backtest', {waitUntil:'networkidle', timeout:120000});
await chip('/backtest');
await p.goto('http://localhost:8503/trade', {waitUntil:'networkidle', timeout:120000});
await chip('/trade (other tab)');
await p.goto('http://localhost:8503/candles', {waitUntil:'networkidle', timeout:120000});
await chip('/candles (other tab)');
await p.screenshot({path:'runjob.png', clip:{x:1000,y:0,width:600,height:110}});
console.log('page errors:', errs);
await b.close();
