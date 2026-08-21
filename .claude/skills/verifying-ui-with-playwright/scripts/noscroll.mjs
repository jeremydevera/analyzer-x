import { chromium } from 'playwright';
const b = await chromium.launch();
const fails = []; const ok = (n,c,d) => { console.log((c?'PASS ':'FAIL ')+n+(d?' — '+d:'')); if(!c) fails.push(n); };
// the narrowest desktop the operator is likely to use, and a wide one
for (const w of [1280, 1512, 1920]) {
  const page = await b.newPage({ viewport: { width: w, height: 1000 } });
  page.on('dialog', d => d.dismiss());
  await page.goto('http://localhost:8503/trade', { waitUntil: 'networkidle' });
  await page.waitForTimeout(6000);
  const m = await page.evaluate(() => {
    const de = document.documentElement;
    const wide = [...document.querySelectorAll('div,table')]
      .filter(el => el.scrollWidth > el.clientWidth + 2)
      .map(el => `${el.tagName}.${(el.className||'').toString().slice(0,40)} ${el.scrollWidth}>${el.clientWidth}`);
    return { doc: de.scrollWidth, client: de.clientWidth, wide: wide.slice(0, 4) };
  });
  ok(`no page-level sideways scroll @${w}`, m.doc <= m.client + 2, `${m.doc} vs ${m.client}`);
  ok(`no inner sideways scroll @${w}`, m.wide.length === 0, m.wide.join(' | '));
  await page.close();
}
console.log(fails.length ? 'RESULT: FAIL ' + fails.join(', ') : 'RESULT: ALL PASS');
await b.close();
