import { chromium } from 'playwright';
const F='file:///private/tmp/claude-501/-Users-jeremydevera-Desktop-Trading-Agents/e6e6f0ce-8b80-438a-80b9-9e9a91eba1f5/scratchpad/deployed-coins-grid.html';
const b = await chromium.launch();
for (const theme of ['light','dark']) {
  const p = await b.newPage({viewport:{width:1500,height:1100}, colorScheme:theme});
  const errs=[]; p.on('pageerror',e=>errs.push(String(e)));
  await p.goto(F,{waitUntil:'networkidle'}); await p.waitForTimeout(1500);
  console.log(theme,'errors:',errs.length?errs:'none');
  console.log(theme,'rows shown:',await p.locator('#tbl tbody tr').count());
  console.log(theme,'cnt:',(await p.locator('#cnt').innerText()).slice(0,90));
  console.log(theme,'foot:',(await p.locator('#foot').innerText()).replace(/\n/g,' | ').slice(0,140));
  // click the deployed PI row
  await p.selectOption('#fonly','dep'); await p.waitForTimeout(500);
  console.log(theme,'live rows:',await p.locator('#tbl tbody tr').count());
  await p.locator('#tbl tbody tr').first().click(); await p.waitForTimeout(900);
  const pan=(await p.locator('#panel').innerText()).replace(/\n/g,' | ');
  console.log(theme,'panel:',pan.slice(0,190));
  console.log(theme,'log rows:',await p.locator('.logscroll tbody tr').count());
  console.log(theme,'total:',(await p.locator('.total').innerText()).replace(/\n/g,' | ').slice(0,130));
  await p.fill('#margin','50'); await p.waitForTimeout(700);
  console.log(theme,'rescaled total:',(await p.locator('.total').innerText()).split('\n')[1]);
  await p.fill('#margin','5'); await p.waitForTimeout(400);
  await p.selectOption('#fonly',''); await p.waitForTimeout(400);
  await p.screenshot({path:`/tmp/g3-${theme}.png`});
  console.log(theme,'h-overflow:',await p.evaluate(()=>document.documentElement.scrollWidth-document.documentElement.clientWidth));
  await p.close();
}
await b.close();
