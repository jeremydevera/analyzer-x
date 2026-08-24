import {chromium} from 'playwright';
const b=await chromium.launch(); const p=await b.newPage({viewport:{width:1500,height:1200}});
const errs=[]; p.on('pageerror',e=>errs.push(String(e).slice(0,160)));
await p.goto('file:///Users/jeremydevera/Desktop/Trading Agents/reports/august-winrate.html',{waitUntil:'load'});
await p.waitForTimeout(1200);
console.log('page errors:', errs.length?errs:'none');
console.log('rows rendered:', await p.locator('tbody#tb tr[data-id]').count());
console.log('columns:', (await p.locator('#hd th').allInnerTexts()).join(' | '));
console.log('count line:', (await p.locator('#count').innerText()).slice(0,120));
console.log('winners:', (await p.locator('.win .co').allInnerTexts()).join('   ||   '));
// click a row -> trade log
await p.locator('tbody#tb tr[data-id]').first().click(); await p.waitForTimeout(500);
const d=await p.locator('#detail').innerText();
console.log('detail has TOTAL PROFIT:', /TOTAL PROFIT/.test(d));
console.log('trade rows in log:', await p.locator('#detail tbody tr').count());
console.log('date format in log:', (d.match(/[A-Z][a-z]{2} \d{2}, \d{4} \d{1,2}:\d{2}[ap]m/)||['NONE'])[0]);
// base margin rescale
const before=(await p.locator('#detail .tot b').first().innerText());
await p.fill('#m','10'); await p.waitForTimeout(400);
const after=(await p.locator('#detail .tot b').first().innerText());
console.log(`base margin 5 -> 10 : ${before} -> ${after}`);
// filters
await p.fill('#m','5'); await p.fill('#wr','70'); await p.waitForTimeout(400);
console.log('min win rate 70 ->', await p.locator('tbody#tb tr[data-id]').count(), 'rows');
await p.fill('#wr',''); await p.fill('#fid','#'+(await p.locator('tbody#tb tr[data-id] .id').first().innerText()).replace('#',''));
await p.waitForTimeout(400);
console.log('find-by-ID ->', await p.locator('tbody#tb tr[data-id]').count(), 'row');
console.log('h-scroll on body:', await p.evaluate(()=>document.body.scrollWidth>window.innerWidth));
await p.fill('#fid',''); await p.waitForTimeout(300);
await p.screenshot({path:'art.png',fullPage:false});
await b.close();
