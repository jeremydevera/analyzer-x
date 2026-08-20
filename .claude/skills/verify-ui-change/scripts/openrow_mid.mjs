import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1900,height:1100});
await p.goto('http://localhost:8503/app/static/bt/openrow-mid.html',
             {waitUntil:'domcontentloaded', timeout:120000});
await p.waitForTimeout(2500);
const opts = await p.evaluate(() => {
  const s = document.getElementById('show');
  return s ? [...s.options].map(o => ({v:o.value, t:o.textContent.trim()})) : null;
});
console.log('show options:', JSON.stringify(opts));
if (opts) {
  const all = opts.find(o => /all/i.test(o.t + o.v)) || opts[opts.length-1];
  await p.selectOption('#show', all.v);
  await p.waitForTimeout(2500);
}
console.log('rows now:', await p.evaluate(()=>document.querySelectorAll('table tbody tr').length));
const fid = await p.$('#fid');
if (fid) { await fid.fill('3M3CRXP8'); await p.waitForTimeout(3000); }
const r = await p.evaluate(() => {
  const box = document.querySelector('.logbox');
  if (!box) return 'no log';
  const rows = [...box.querySelectorAll('tbody tr')];
  const last = rows[rows.length-1];
  const c = [...last.querySelectorAll('td')].map(td=>td.innerText.trim());
  return {logRows: rows.length, lastClass: last.className,
          last: {n:c[0], opened:c[1], closed:c[2], held:c[3], side:c[4],
                 closedBy:c[5], entry:c[6], exit:c[7], profit:c[13]},
          footer: [...box.querySelectorAll('tfoot tr')]
                    .map(t=>t.innerText.replace(/\s+/g,' ').trim())};
});
console.log(JSON.stringify(r,null,1));
await p.screenshot({path:'openrow_mid.png'});
await b.close();
