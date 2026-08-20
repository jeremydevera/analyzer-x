import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
const errs=[], logs=[];
p.on('pageerror', e => errs.push(String(e).slice(0,200)));
p.on('console', m => { if (m.type()==='error') logs.push(m.text().slice(0,200)); });
await p.setViewportSize({width:1900,height:1100});
await p.goto('http://localhost:8503/app/static/bt/openrow-check.html',
             {waitUntil:'domcontentloaded', timeout:120000});
await p.waitForTimeout(3000);
const st = await p.evaluate(() => ({
  hasRows: typeof rows !== 'undefined' ? rows.length : 'rows undefined',
  hasData: typeof DATA !== 'undefined' ? Object.keys(DATA).length : 'DATA undefined',
  dataRows: typeof DATA !== 'undefined' && DATA.rows ? DATA.rows.length : null,
  dataCols: typeof DATA !== 'undefined' && DATA.cols ? DATA.cols.length : null,
}));
console.log('page state:', JSON.stringify(st));
console.log('pageerrors:', errs);
console.log('console errors:', logs);
await b.close();
