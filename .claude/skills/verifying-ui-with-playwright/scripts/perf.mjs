import { chromium } from 'playwright';
const b = await chromium.launch();
const run = async (label) => {
  const p = await b.newPage();
  await p.setViewportSize({width:1600,height:1100});
  const t0 = Date.now();
  await p.goto('http://localhost:8503', {waitUntil:'domcontentloaded', timeout:180000});
  const tDom = Date.now()-t0;
  // wait until the account hero number actually renders = screen is usable
  let tReady = null;
  try {
    await p.waitForFunction(() => /\d{2,3}\.\d\d/.test(
      document.querySelector('.mv-hero, .mv-big, [class*="mv-"]')?.innerText || ''
    ), {timeout: 180000});
    tReady = Date.now()-t0;
  } catch { tReady = -1; }
  const rows = await p.evaluate(()=>document.querySelectorAll('.mv-str > div:not(.hd)').length);
  await p.close();
  console.log(`${label.padEnd(12)} dom ${String(tDom).padStart(6)}ms   usable ${String(tReady).padStart(6)}ms   strategyRows ${rows}`);
  return tReady;
};
await run('cold');
await run('warm-1');
await run('warm-2');
await b.close();
