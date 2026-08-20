import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1900,height:1100});
await p.goto('http://localhost:8503/app/static/bt/openrow-check.html',
             {waitUntil:'domcontentloaded', timeout:120000});
await p.waitForTimeout(3000);
// open the deployed row's log
// click the first data row to open its log; the find-by-id box may not be
// present in every build
const fid = await p.$('#fid');
if (fid) { await fid.fill('3M3CRXP8'); await p.waitForTimeout(2500); }
if (!(await p.$('.logbox'))) {
  const row = await p.$('table tbody tr');
  if (row) { await row.click(); await p.waitForTimeout(2500); }
}
if (!(await p.$('.logbox'))) {
  console.log('diag:', await p.evaluate(() => ({
    hasFid: !!document.getElementById('fid'),
    tables: document.querySelectorAll('table').length,
    bodyRows: document.querySelectorAll('table tbody tr').length,
    firstRowText: (document.querySelector('table tbody tr')||{}).innerText?.slice(0,80),
    err: window.__lastErr || null})));
}
const r = await p.evaluate(() => {
  const box = document.querySelector('.logbox');
  if (!box) return 'no log open';
  const rows = [...box.querySelectorAll('tbody tr')];
  const last = rows[rows.length-1];
  const cells = [...last.querySelectorAll('td')].map(td=>td.innerText.trim());
  const foot = [...box.querySelectorAll('tfoot tr')].map(tr=>tr.innerText.replace(/\s+/g,' ').trim());
  return {rowCount: rows.length,
          lastRowClass: last.className,
          lastRow: {n:cells[0], opened:cells[1], closed:cells[2], closedBy:cells[5],
                    entry:cells[6], exit:cells[7], profit:cells[13]},
          footer: foot};
});
console.log(JSON.stringify(r,null,1));
await p.screenshot({path:'openrow.png', fullPage:false});
await b.close();
