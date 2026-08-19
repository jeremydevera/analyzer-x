import { chromium } from 'playwright';
const F='file:///private/tmp/claude-501/-Users-jeremydevera-Desktop-Trading-Agents/e6e6f0ce-8b80-438a-80b9-9e9a91eba1f5/scratchpad/audit.html';
const b = await chromium.launch();
for (const theme of ['light','dark']) {
  const p = await b.newPage({viewport:{width:1400,height:1050}, colorScheme:theme});
  const errs=[]; p.on('pageerror',e=>errs.push(String(e))); p.on('console',m=>{if(m.type()==='error')errs.push(m.text())});
  await p.goto(F,{waitUntil:'networkidle'});
  await p.waitForTimeout(700);
  console.log(theme,'JS errors:',errs.length?errs:'none');
  console.log(theme,'rows:',await p.locator('#tbl tbody tr').count());
  console.log(theme,'foot:',(await p.locator('#foot').innerText()).replace(/\n/g,' | '));
  console.log(theme,'cnt:',await p.locator('#cnt').innerText());
  console.log(theme,'verdict cards:',await p.locator('.vstat').count());
  await p.screenshot({path:`/tmp/audit-${theme}-top.png`});
  // click the first fabricated row
  const rows = p.locator('#tbl tbody tr');
  const n = await rows.count();
  for (let i=0;i<n;i++){ if((await rows.nth(i).innerText()).toLowerCase().includes('fabricated')){ await rows.nth(i).click(); break; } }
  await p.waitForTimeout(500);
  console.log(theme,'panel total:',(await p.locator('.total').innerText()).replace(/\n/g,' | '));
  console.log(theme,'log rows:',await p.locator('.logscroll tbody tr').count());
  console.log(theme,'canvas h:',await p.locator('#cv').evaluate(c=>c.height));
  await p.locator('#panel').screenshot({path:`/tmp/audit-${theme}-panel.png`});
  // margin rescale check
  const before = await p.locator('#foot td').last().innerText();
  await p.fill('#margin','50');
  await p.waitForTimeout(400);
  const after = await p.locator('#foot td').last().innerText();
  console.log(theme,'rescale 5->50:',before,'=>',after);
  // horizontal body scroll check
  console.log(theme,'body overflow:',await p.evaluate(()=>document.documentElement.scrollWidth-document.documentElement.clientWidth));
  await p.close();
}
await b.close();
