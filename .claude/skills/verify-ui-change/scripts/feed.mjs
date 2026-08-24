import {chromium} from 'playwright';
const b=await chromium.launch(); const p=await b.newPage({viewport:{width:1700,height:1400}});
// NEVER networkidle: the page polls
await p.goto('http://localhost:8503/trade',{waitUntil:'domcontentloaded',timeout:120000});
await p.waitForTimeout(10000);
const txt = await p.evaluate(()=>{
  const el=[...document.querySelectorAll('pre,code,div')]
    .filter(e=>/INFO scan /.test(e.textContent||''))
    .sort((a,b)=>a.textContent.length-b.textContent.length)[0];
  return el ? el.innerText : null;
});
if(!txt){ console.log('(no log block on the page)'); }
else {
  const lines = txt.split('\n').map(l=>l.trim()).filter(l=>/INFO|WARNING/.test(l));
  console.log('total feed lines:', lines.length);
  console.log('newest 3:');
  lines.slice(-3).forEach(l=>console.log('  '+l.slice(0,118)));
  const iso = lines.filter(l=>/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}/.test(l)).length;
  const ok  = lines.filter(l=>/^[A-Z][a-z]{2} \d{2}, \d{4} \d{1,2}:\d{2}[ap]m/.test(l)).length;
  console.log(`\nISO-stamped (banned): ${iso}`);
  console.log(`operator format:      ${ok}`);
}
await b.close();
