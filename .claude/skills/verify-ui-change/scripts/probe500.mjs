import { chromium } from 'playwright-core';
const b = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' });
const p = await b.newPage({ viewport: { width: 1600, height: 1200 } });
const bad = [];
p.on('response', r => { if (r.status() >= 400) bad.push(r.status() + ' ' + r.url()); });
await p.goto('http://localhost:8503/backtest', { waitUntil: 'load', timeout: 90000 }).catch(e => console.log('goto', String(e).slice(0,120)));
await p.waitForTimeout(6000);
console.log('bad responses:'); bad.slice(0, 12).forEach(x => console.log(' ', x));
const css = await p.evaluate(() => ({
  sheets: document.styleSheets.length,
  bodyBg: getComputedStyle(document.body).backgroundColor,
  links: [...document.querySelectorAll('link[rel=stylesheet]')].map(l => l.href),
}));
console.log(JSON.stringify(css, null, 1));
await b.close();
