import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
const errs=[]; p.on('pageerror',e=>errs.push(String(e).slice(0,140)));
await p.setViewportSize({width:1600,height:1000});
await p.goto('http://localhost:8503/trade', {waitUntil:'networkidle', timeout:120000});
await p.waitForTimeout(3500);
const r = await p.evaluate(() => {
  const bell = document.querySelector('button[aria-label^="notifications"]');
  const theme = [...document.querySelectorAll('button')]
    .find(b => /theme|dark|light/i.test(b.getAttribute('aria-label')||b.className||''));
  const heads = [...document.querySelectorAll('th, [class*="TableCell"]')]
    .map(e=>e.innerText.trim()).filter(Boolean).slice(0,20);
  const txt = document.body.innerText;
  return {
    bellPresent: !!bell,
    bellBox: bell ? bell.getBoundingClientRect().width + 'x' + bell.getBoundingClientRect().height : null,
    bellRight: bell ? Math.round(bell.getBoundingClientRect().left) : null,
    themeRight: theme ? Math.round(theme.getBoundingClientRect().left) : null,
    hasOpenNow: /open now/i.test(txt),
    hasNotional: /notional/i.test(txt),
    hasIdHash: /#[0-9A-Z]{8}/.test(txt),
    idSample: (txt.match(/#[0-9A-Z]{8}/g)||[]).slice(0,3),
    liveDemoSwitches: (txt.match(/\blive\b/gi)||[]).length,
  };
});
console.log(JSON.stringify(r,null,1));
console.log('page errors:', errs);
await b.close();
