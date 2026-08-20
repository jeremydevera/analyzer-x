import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
const errs=[]; p.on('pageerror',e=>errs.push(String(e).slice(0,110)));
await p.setViewportSize({width:1600,height:1050});
await p.goto('http://localhost:8503', {waitUntil:'domcontentloaded', timeout:120000});
await p.waitForFunction(()=>document.querySelectorAll('.nvx-i').length>0,{timeout:120000});
await p.waitForTimeout(1500);
for (const want of ['Back Test','New Crypto','LLM Models','Auto Trade']) {
  const t0 = Date.now();
  await p.click(`.nvx-i:has(.nvx-l:text-is("${want}"))`);
  await p.waitForFunction((w)=>{
    const on = document.querySelector('.nvx-i.on .nvx-l');
    const h1 = document.querySelector('h1.ta-page-title');
    return on && on.innerText.trim()===w && h1 && h1.innerText.trim()===w;
  }, want, {timeout:60000}).catch(()=>{});
  const st = await p.evaluate(() => ({
    active: document.querySelector('.nvx-i.on .nvx-l')?.innerText.trim(),
    title: document.querySelector('h1.ta-page-title')?.innerText.trim(),
    url: location.search }));
  console.log(`${want.padEnd(12)} -> active=${String(st.active).padEnd(12)} title=${String(st.title).padEnd(12)} ${st.url}  ${Date.now()-t0}ms  ${st.active===want&&st.title===want?'OK':'MISMATCH'}`);
}
console.log('errors', errs);
await p.screenshot({path:'rail_final.png'});
await b.close();
