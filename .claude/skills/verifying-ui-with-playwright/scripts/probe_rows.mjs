import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage({viewport:{width:1680,height:1400}});
p.on('dialog', d => d.dismiss());
await p.goto('http://localhost:3000/trade', {waitUntil:'networkidle'});
await p.waitForTimeout(4500);
console.log(JSON.stringify(await p.evaluate(() => {
  const tables = [...document.querySelectorAll('table')];
  const t = tables.find(t => t.textContent.includes('unrealized'));
  return [...(t?.querySelectorAll('tbody tr') ?? [])].slice(0,6)
    .map(tr => [...tr.querySelectorAll('td')].map(td => td.textContent.trim()));
}), null, 1));
await b.close();
