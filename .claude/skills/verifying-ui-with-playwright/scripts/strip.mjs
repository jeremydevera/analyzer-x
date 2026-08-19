import { chromium } from 'playwright';
const b = await chromium.launch();
for (const theme of ['light','dark']) {
  const p = await b.newPage({viewport:{width:1500,height:1100}, colorScheme:theme});
  const errs=[]; p.on('pageerror',e=>errs.push(String(e)));
  await p.goto('http://localhost:8503',{waitUntil:'networkidle'});
  await p.waitForTimeout(9000);
  await p.getByText('Auto Trade',{exact:true}).first().click();
  await p.waitForTimeout(13000);
  console.log(theme,'errors:',errs.length?errs:'none');
  const wallet = p.getByText(/FUTURES WALLET/i).first().locator('xpath=..');
  const runner = p.getByText(/^RUNNER$/i).first().locator('xpath=..');
  const a = await wallet.boundingBox(), z = await runner.boundingBox();
  console.log(theme,'strip spans x', Math.round(a.x), '->', Math.round(z.x+z.width));
  await p.screenshot({path:`/tmp/strip-${theme}.png`, clip:{x:a.x-10,y:a.y-26,width:(z.x+z.width)-a.x+20,height:Math.max(a.height,z.height)+46}});
  console.log(theme,'h-overflow:', await p.evaluate(()=>document.documentElement.scrollWidth-document.documentElement.clientWidth));
  await p.close();
}
await b.close();
