import { chromium } from 'playwright';
import fs from 'fs';
const b = await chromium.launch(); const p = await b.newPage();
await p.setViewportSize({width:1600,height:1000});
const BASE='https://zenith-shadcn.dashboardpack.com';
await p.goto(BASE+'/dashboard', {waitUntil:'networkidle', timeout:120000});
await p.waitForTimeout(5000);

const out = await p.evaluate(() => {
  const rs = getComputedStyle(document.documentElement);
  const varNames = [];
  for (const sheet of document.styleSheets) {
    let rules; try { rules = sheet.cssRules } catch { continue }
    for (const r of rules||[]) {
      if (r.style) for (const prop of r.style) if (prop.startsWith('--')) varNames.push(prop);
      if (r.cssRules) for (const q of r.cssRules) if (q.style)
        for (const prop of q.style) if (prop.startsWith('--')) varNames.push(prop);
    }
  }
  const tokens = {};
  for (const v of [...new Set(varNames)].sort()) {
    const val = rs.getPropertyValue(v).trim();
    if (val) tokens[v] = val;
  }
  const grab = (sel, keys) => {
    const el = document.querySelector(sel); if (!el) return null;
    const cs = getComputedStyle(el); const o = {_sel: sel};
    for (const k of keys) o[k] = cs[k];
    o._rect = (({width,height}) => ({w:Math.round(width), h:Math.round(height)}))(el.getBoundingClientRect());
    return o;
  };
  const BOX = ['backgroundColor','color','borderColor','borderWidth','borderStyle',
               'borderRadius','boxShadow','padding','fontFamily','fontSize','fontWeight',
               'letterSpacing','lineHeight'];
  return {
    tokens,
    fonts: {body: getComputedStyle(document.body).fontFamily,
            bodySize: getComputedStyle(document.body).fontSize},
    theme: document.documentElement.className + ' | ' + (document.documentElement.dataset.theme||''),
    components: {
      card:      grab('[class*="card"], .rounded-xl.border', BOX),
      table:     grab('table', BOX),
      th:        grab('th', BOX),
      td:        grab('td', BOX),
      btnPrimary:grab('button', BOX),
      input:     grab('input', BOX),
      badge:     grab('[class*="badge"], span[class*="rounded-full"]', BOX),
      sidebar:   grab('[class*="sidebar"], aside, nav', BOX),
      heading:   grab('h1,h2', BOX),
    },
    headings: [...document.querySelectorAll('h1,h2,h3')].map(h=>h.innerText.trim()).slice(0,14),
    navItems: [...document.querySelectorAll('aside a, nav a')].map(a=>a.innerText.trim()).filter(Boolean).slice(0,24),
  };
});
fs.writeFileSync('dp_tokens.json', JSON.stringify(out,null,1));
console.log('theme:', out.theme);
console.log('fonts:', JSON.stringify(out.fonts));
console.log('token count:', Object.keys(out.tokens).length);
console.log('nav:', JSON.stringify(out.navItems));
console.log('headings:', JSON.stringify(out.headings));
await p.screenshot({path:'dp_dash.png', fullPage:false});
await b.close();
