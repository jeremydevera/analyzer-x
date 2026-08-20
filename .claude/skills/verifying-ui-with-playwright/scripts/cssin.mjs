import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.goto('http://localhost:8503', {waitUntil:'networkidle', timeout:120000});
await p.waitForTimeout(9000);
await p.getByText('Back Test', {exact:true}).first().click();
await p.waitForTimeout(6000);
const r = await p.evaluate(() => {
  const all = [...document.querySelectorAll('style')].map(s=>s.textContent).join('\n');
  return {
    hasDisabledRule: /button:disabled/.test(all),
    hasMetricRule: /stMetricLabel/.test(all),
    styleTags: document.querySelectorAll('style').length,
  };
});
console.log(JSON.stringify(r));
await b.close();
