import { chromium } from 'playwright';
const b = await chromium.launch();
for (const theme of ['light','dark']) {
  const p = await b.newPage({viewport:{width:1500,height:1100}, colorScheme:theme});
  const errs=[]; p.on('pageerror',e=>errs.push(String(e)));
  await p.goto('http://localhost:8503',{waitUntil:'networkidle'});
  await p.waitForTimeout(9000);
  await p.getByText('Auto Trade',{exact:true}).first().click();
  await p.waitForTimeout(13000);
  const names=[/FUTURES WALLET/i,/REAL PNL NOW/i,/PAPER PNL NOW/i,/^RUNNER$/i];
  const boxes=[];
  for (const n of names){ const el=p.getByText(n).first().locator('xpath=..');
    boxes.push(await el.boundingBox()); }
  const ys = boxes.map(b=>Math.round(b.y));
  console.log(theme,'errors:',errs.length?errs:'none');
  console.log(theme,'tile y:',ys, ys.every(y=>y===ys[0])?'ALL ON ONE ROW':'*** WRAPPED ***');
  console.log(theme,'tile w:',boxes.map(b=>Math.round(b.width)));
  console.log(theme,'tile h:',boxes.map(b=>Math.round(b.height)));
  const x0=Math.min(...boxes.map(b=>b.x)), x1=Math.max(...boxes.map(b=>b.x+b.width));
  const y0=Math.min(...ys), y1=Math.max(...boxes.map(b=>b.y+b.height));
  await p.screenshot({path:`/tmp/strip-${theme}.png`, clip:{x:x0-10,y:y0-10,width:x1-x0+20,height:y1-y0+20}});
  console.log(theme,'h-overflow:', await p.evaluate(()=>document.documentElement.scrollWidth-document.documentElement.clientWidth));
  await p.close();
}
await b.close();
