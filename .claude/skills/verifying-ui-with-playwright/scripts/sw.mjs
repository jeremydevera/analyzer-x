import { chromium } from 'playwright';
const F='file:///private/tmp/claude-501/-Users-jeremydevera-Desktop-Trading-Agents/e6e6f0ce-8b80-438a-80b9-9e9a91eba1f5/scratchpad/all-coins-sweep.html';
const b = await chromium.launch();
for (const theme of ['light','dark']) {
  const p = await b.newPage({viewport:{width:1500,height:1100}, colorScheme:theme});
  const errs=[]; p.on('pageerror',e=>errs.push(String(e)));
  await p.goto(F,{waitUntil:'networkidle'}); await p.waitForTimeout(1200);
  console.log(theme,'errors:',errs.length?errs:'none');
  console.log(theme,'coverage:',(await p.locator('#coverage').innerText()).slice(0,120));
  console.log(theme,'cards:',(await p.locator('#verdict').innerText()).replace(/\n/g,' | ').slice(0,240));
  console.log(theme,'rows(survivors):',await p.locator('#tbl tbody tr').count());
  await p.selectOption('#fq',''); await p.waitForTimeout(400);
  console.log(theme,'rows(all):',await p.locator('#tbl tbody tr').count());
  console.log(theme,'foot:',(await p.locator('#foot').innerText()).replace(/\n/g,' | ').slice(0,120));
  await p.selectOption('#fq','surv'); await p.waitForTimeout(400);
  // click first row that has a log
  const rows=p.locator('#tbl tbody tr'); let clicked=false;
  for(let i=0;i<Math.min(await rows.count(),25);i++){
    if(/\blog\b/i.test(await rows.nth(i).innerText())){ await rows.nth(i).click(); clicked=true; break; }}
  await p.waitForTimeout(700);
  console.log(theme,'clicked a log row:',clicked,'| log rows:',await p.locator('.logscroll tbody tr').count());
  console.log(theme,'total:',(await p.locator('.total').innerText()).replace(/\n/g,' | ').slice(0,120));
  const before=await p.locator('#foot td').nth(5).innerText();
  await p.fill('#margin','50'); await p.waitForTimeout(600);
  console.log(theme,'rescale 5->50:',before,'=>',await p.locator('#foot td').nth(5).innerText());
  await p.fill('#margin','5'); await p.waitForTimeout(300);
  await p.screenshot({path:`/tmp/sw-${theme}.png`});
  console.log(theme,'h-overflow:',await p.evaluate(()=>document.documentElement.scrollWidth-document.documentElement.clientWidth));
  await p.close();
}
await b.close();
