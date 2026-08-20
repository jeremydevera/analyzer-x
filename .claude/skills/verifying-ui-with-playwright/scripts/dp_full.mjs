import { chromium } from 'playwright';
import fs from 'fs';
const b = await chromium.launch(); const p = await b.newPage();
const BASE='https://zenith-shadcn.dashboardpack.com';
const BOX=['backgroundColor','color','borderColor','borderTopWidth','borderRadius','boxShadow',
           'padding','paddingLeft','paddingTop','fontFamily','fontSize','fontWeight',
           'letterSpacing','lineHeight','textTransform','gap','height','minHeight'];

const snap = () => p.evaluate((BOX) => {
  const rs=getComputedStyle(document.documentElement);
  const tok={};
  for (const k of ['--background','--foreground','--card','--card-foreground','--border',
    '--primary','--primary-foreground','--secondary','--muted','--muted-foreground',
    '--accent','--destructive','--radius','--card-padding','--sidebar','--sidebar-foreground',
    '--sidebar-accent','--sidebar-border','--chart-1','--chart-2','--chart-3','--chart-4','--chart-5',
    '--ring','--input','--popover'])
    tok[k]=rs.getPropertyValue(k).trim();
  const g=(sel)=>{ const el=document.querySelector(sel); if(!el) return null;
    const cs=getComputedStyle(el); const o={_sel:sel};
    for(const k of BOX) o[k]=cs[k];
    const r=el.getBoundingClientRect(); o._w=Math.round(r.width); o._h=Math.round(r.height);
    return o; };
  // find the real sidebar by looking for the nav that contains "Dashboard"
  const side=[...document.querySelectorAll('aside,nav,div')].find(e=>{
    const r=e.getBoundingClientRect();
    return r.width>180 && r.width<340 && r.height>500 && /Dashboard/.test(e.innerText||'');
  });
  const activeNav=[...document.querySelectorAll('a')].find(a=>/^Dashboard$/.test(a.innerText.trim()));
  return {theme:document.documentElement.className, tok,
    sidebar: side?{bg:getComputedStyle(side).backgroundColor, w:Math.round(side.getBoundingClientRect().width),
                   color:getComputedStyle(side).color}:null,
    activeNav: activeNav?{bg:getComputedStyle(activeNav).backgroundColor,
                          color:getComputedStyle(activeNav).color,
                          radius:getComputedStyle(activeNav).borderRadius,
                          pad:getComputedStyle(activeNav).padding,
                          h:Math.round(activeNav.getBoundingClientRect().height),
                          fs:getComputedStyle(activeNav).fontSize}:null,
    card:g('.rounded-xl.border, [data-slot="card"]'), btn:g('button'), input:g('input'),
    h1:g('h1'), table:g('table'), th:g('th'), td:g('td'),
  };
}, BOX);

await p.setViewportSize({width:1600,height:1000});
await p.goto(BASE+'/dashboard', {waitUntil:'networkidle', timeout:120000});
await p.waitForTimeout(5000);
const light = await snap();

// toggle to dark: the moon button in the top bar
const btns = await p.$$('button');
for (const btn of btns) {
  const t = await btn.getAttribute('aria-label') || await btn.innerText().catch(()=>'') || '';
  const html = await btn.innerHTML().catch(()=>'');
  if (/moon|theme|dark/i.test(t+html)) { await btn.click().catch(()=>{}); break; }
}
await p.waitForTimeout(2500);
let dark = await snap();
if (!/dark/.test(dark.theme)) {
  await p.evaluate(()=>document.documentElement.classList.add('dark'));
  await p.waitForTimeout(1500);
  dark = await snap();
}
await p.screenshot({path:'dp_dark.png'});

// a table-heavy page
await p.goto(BASE+'/orders', {waitUntil:'networkidle', timeout:120000}).catch(()=>{});
await p.waitForTimeout(4000);
const orders = await snap();
await p.screenshot({path:'dp_orders.png'});

// responsive
const resp=[];
for (const w of [375,768,1024,1440]) {
  await p.setViewportSize({width:w,height:900}); await p.waitForTimeout(2000);
  resp.push(await p.evaluate((w)=>({w, hscroll: document.documentElement.scrollWidth>window.innerWidth+1,
    sidebarVisible: (()=>{ const s=[...document.querySelectorAll('aside,nav')].find(e=>/Dashboard/.test(e.innerText||''));
      if(!s) return 'none'; const r=s.getBoundingClientRect();
      return r.width>0 && r.left>-10 ? Math.round(r.width)+'px' : 'offscreen'; })(),
    cols: (()=>{ const g=document.querySelector('[class*="grid"]'); return g?getComputedStyle(g).gridTemplateColumns:''})()
  }), w));
  await p.screenshot({path:`dp_${w}.png`});
}
fs.writeFileSync('dp_full.json', JSON.stringify({light,dark,orders,resp},null,1));
console.log('LIGHT theme:', light.theme);
console.log('  sidebar', JSON.stringify(light.sidebar), '\n  activeNav', JSON.stringify(light.activeNav));
console.log('  card', JSON.stringify(light.card));
console.log('DARK theme:', dark.theme);
console.log('  tok', JSON.stringify(dark.tok));
console.log('  sidebar', JSON.stringify(dark.sidebar));
console.log('TABLE th', JSON.stringify(orders.th), '\n  td', JSON.stringify(orders.td));
console.log('RESP', JSON.stringify(resp));
await b.close();
