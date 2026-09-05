import { chromium } from 'playwright-core';
const URL = process.env.U || 'http://localhost:8503/backtest';
const OUT = process.env.O || 'filters_before';
const b = await chromium.launch({
  executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
});
const p = await b.newPage({ viewport: { width: 1600, height: 1200 } });
p.on('console', m => { if (m.type() === 'error') console.log('console error:', m.text().slice(0, 200)); });
p.on('pageerror', e => console.log('pageerror:', String(e).slice(0, 200)));
await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 90000 });
await p.waitForTimeout(8000);
console.log('title:', await p.title());
console.log('headings:', JSON.stringify(await p.evaluate(
  () => [...document.querySelectorAll('h1,h2,h3,h4')].map(x => x.innerText.trim()).slice(0, 14))));
await p.screenshot({ path: `${OUT}_page.png`, fullPage: true });
await b.close();
