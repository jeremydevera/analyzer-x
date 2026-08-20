import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1600,height:1100});
await p.goto('http://localhost:8503', {waitUntil:'domcontentloaded', timeout:120000});

await p.waitForFunction(()=>document.querySelectorAll('.mv').length>0,{timeout:120000});
await p.waitForTimeout(2500);
const r = await p.evaluate(() => {
  const rs = getComputedStyle(document.documentElement);
  const raw = {};
  for (const t of ['--n-0','--n-2','--n-9','--sf-page','--sf-raised','--fg','--hair',
                   '--bg','--panel','--text','--muted','--faint','--accent'])
    raw[t] = rs.getPropertyValue(t).trim();
  // what the browser actually computes them to
  const s = document.createElement('span'); document.body.appendChild(s);
  const res = {};
  for (const t of ['--sf-page','--sf-raised','--fg','--bg','--panel','--text','--muted'])
    { s.style.color = `var(${t})`; res[t] = getComputedStyle(s).color; }
  s.remove();
  const app = document.querySelector('.stApp');
  const mvc = document.querySelector('.mv-cell');
  return {raw, res,
    appBg: getComputedStyle(app).backgroundColor,
    bodyBg: getComputedStyle(document.body).backgroundColor,
    cellBg: mvc ? getComputedStyle(mvc).backgroundColor : null,
    cellColor: mvc ? getComputedStyle(mvc).color : null};
});
console.log(JSON.stringify(r,null,1));
await b.close();
