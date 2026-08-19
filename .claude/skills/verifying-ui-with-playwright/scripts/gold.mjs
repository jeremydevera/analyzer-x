import { chromium } from 'playwright';
const F='file:///private/tmp/claude-501/-Users-jeremydevera-Desktop-Trading-Agents/e6e6f0ce-8b80-438a-80b9-9e9a91eba1f5/scratchpad/gold-1h-verification.html';
const b = await chromium.launch();
for (const theme of ['light','dark']) {
  const p = await b.newPage({viewport:{width:1500,height:1100}, colorScheme:theme});
  const errs=[]; p.on('pageerror',e=>errs.push(String(e)));
  await p.goto(F,{waitUntil:'networkidle'}); await p.waitForTimeout(900);
  console.log(theme,'errors:',errs.length?errs:'none');
  console.log(theme,'rows(asked):',await p.locator('#tbl tbody tr').count());
  console.log(theme,'cnt:',(await p.locator('#cnt').innerText()).slice(0,110));
  console.log(theme,'foot:',(await p.locator('#foot').innerText()).replace(/\n/g,' | '));
  await p.selectOption('#filt','all'); await p.waitForTimeout(400);
  console.log(theme,'rows(all):',await p.locator('#tbl tbody tr').count());
  await p.locator('#tbl tbody tr').first().click(); await p.waitForTimeout(600);
  console.log(theme,'log rows:',await p.locator('.logscroll tbody tr').count());
  console.log(theme,'panel total:',(await p.locator('.total').innerText()).replace(/\n/g,' | ').slice(0,150));
  const before=await p.locator('#foot td').nth(5).innerText();
  await p.fill('#margin','100'); await p.waitForTimeout(500);
  console.log(theme,'rescale 10->100:',before,'=>',await p.locator('#foot td').nth(5).innerText());
  await p.fill('#margin','10'); await p.waitForTimeout(300);
  await p.screenshot({path:`/tmp/gold-${theme}.png`});
  console.log(theme,'h-overflow:',await p.evaluate(()=>document.documentElement.scrollWidth-document.documentElement.clientWidth));
  await p.close();
}
await b.close();
