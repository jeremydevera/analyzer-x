import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.goto('http://localhost:8503', {waitUntil:'networkidle', timeout:120000});
await p.waitForTimeout(9000);
const dump = async (label) => {
  const r = await p.evaluate(() => {
    const tags = [...document.querySelectorAll('style')];
    return {n: tags.length,
      heads: tags.map(t=>({len:t.textContent.length, head:t.textContent.replace(/\s+/g,' ').slice(0,90)})),
      anyDisabled: tags.some(t=>/button:disabled/.test(t.textContent)),
      anyFaint: tags.some(t=>/--faint:#7f8ea6/.test(t.textContent)),
      anyMetric: tags.some(t=>/stMetricLabel/.test(t.textContent))};
  });
  console.log('==', label, JSON.stringify(r,null,1));
};
await dump('Auto Trade');
await p.getByText('Back Test', {exact:true}).first().click();
await p.waitForTimeout(6000);
await dump('Back Test');
await b.close();
