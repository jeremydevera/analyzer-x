import { chromium } from 'playwright';
const b = await chromium.launch();
for (const theme of ['light','dark']) {
  const p = await b.newPage({viewport:{width:1500,height:1100}, colorScheme:theme});
  const errs=[]; p.on('pageerror',e=>errs.push(String(e)));
  await p.goto('http://localhost:8503',{waitUntil:'networkidle'});
  await p.waitForTimeout(9000);
  await p.getByText('Auto Trade',{exact:true}).first().click();
  await p.waitForTimeout(13000);
  // the strip is the flex row that CONTAINS the Futures wallet tile
  const row = p.getByText(/FUTURES WALLET/i).first().locator('xpath=../..');
  const kids = row.locator(':scope > div');
  const n = await kids.count();
  console.log(theme,'errors:',errs.length?errs:'none','| tiles in strip:',n);
  const ys=[];
  for (let i=0;i<n;i++){
    const bb = await kids.nth(i).boundingBox();
    const t = (await kids.nth(i).innerText()).replace(/\n/g,' ').slice(0,46);
    ys.push(Math.round(bb.y));
    console.log(`   tile[${i}] x=${Math.round(bb.x)} y=${Math.round(bb.y)} w=${Math.round(bb.width)} h=${Math.round(bb.height)}  ${t}`);
  }
  console.log(theme, ys.every(y=>y===ys[0]) ? '=> ALL ON ONE ROW' : '=> *** WRAPPED ***');
  const bb = await row.boundingBox();
  await p.screenshot({path:`/tmp/strip-${theme}.png`, clip:{x:bb.x-10,y:bb.y-10,width:bb.width+20,height:bb.height+20}});
  await p.close();
}
await b.close();
