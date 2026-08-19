import { chromium } from 'playwright';
const b = await chromium.launch();
for (const theme of ['light','dark']) {
  const p = await b.newPage({viewport:{width:1500,height:1100}, colorScheme:theme});
  const errs=[]; p.on('pageerror',e=>errs.push(String(e)));
  await p.goto('http://localhost:8503',{waitUntil:'networkidle'});
  await p.waitForTimeout(9000);
  await p.getByText('Auto Trade',{exact:true}).first().click();
  await p.waitForTimeout(12000);
  console.log(theme,'JS errors:', errs.length?errs:'none');
  console.log(theme,'stray line gone:', !(await p.getByText(/today.s real closes/i).count()));
  const tile = p.getByText(/REAL PNL NOW/i).first().locator('xpath=..');
  const t = (await tile.innerText()).replace(/\n/g,' | ');
  console.log(theme,'TILE:', t);
  const bb = await tile.boundingBox();
  console.log(theme,'tile box:', bb ? `x=${Math.round(bb.x)} y=${Math.round(bb.y)} w=${Math.round(bb.width)} h=${Math.round(bb.height)}` : 'none');
  // compare heights of the four tiles - they should not be wildly mismatched
  const cells = p.locator('xpath=//div[contains(text(),"Futures wallet") or contains(text(),"FUTURES WALLET")]/..');
  await tile.scrollIntoViewIfNeeded(); await p.waitForTimeout(900);
  await p.screenshot({path:`/tmp/tile-${theme}.png`});
  console.log(theme,'h-overflow:', await p.evaluate(()=>document.documentElement.scrollWidth-document.documentElement.clientWidth));
  await p.close();
}
await b.close();
