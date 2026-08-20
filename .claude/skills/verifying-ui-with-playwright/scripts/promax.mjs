import { chromium } from "playwright";
const b = await chromium.launch();
const pg = await b.newPage({ viewport: { width: 1800, height: 1700 } });
const errs = []; pg.on("pageerror", e => errs.push(String(e)));
await pg.goto("http://localhost:8503", { waitUntil: "networkidle" });
await pg.waitForTimeout(12000);
const side = pg.locator('[data-testid="stSidebar"]');
for (let a=0;a<3;a++){
  const btn = side.locator("button", { hasText: /^Auto Trade$/ }).first();
  if (await btn.count() && await btn.isVisible()) { await btn.click({force:true}); await pg.waitForTimeout(10000); }
  if (await pg.locator('.mv-hero').count()) break;
}
// contrast helper
const rel = (c) => { const [r,g,bb]=c.match(/\d+(\.\d+)?/g).slice(0,3).map(Number).map(v=>{v/=255;return v<=.03928?v/12.92:Math.pow((v+.055)/1.055,2.4)}); return .2126*r+.7152*g+.0722*bb; };
const out = await pg.evaluate(() => {
  const root=getComputedStyle(document.documentElement);
  const q=(s)=>document.querySelectorAll(s).length;
  const fam=(s)=>{const e=document.querySelector(s);return e?getComputedStyle(e).fontFamily.split(",")[0]:null};
  return {
    tokens:{bg:root.getPropertyValue('--bg').trim(), panel:root.getPropertyValue('--panel').trim(),
      border:root.getPropertyValue('--border').trim(), accent:root.getPropertyValue('--accent').trim(),
      muted:root.getPropertyValue('--muted').trim()},
    fonts:{body:fam('body'), num:fam('.mv-num'), hero:fam('.mv-hero .v')},
    dupes:{ribbon:q('.tm-rib'), perfBand:q('.an-grid'), oldPos:q('.st-key-pos_real')},
    view:{hero:q('.mv-hero'), cells:q('.mv-cell'), rows:q('.mv-row:not(.hd):not(.ft)'),
      rings:q('.mv-ring'), svgIcons:q('.mv-cell em svg'), glyphs:document.body.innerText.match(/[◈◷◇Σ●]/g)?.length||0},
    colours:{text:getComputedStyle(document.querySelector('.mv-hero .v')).color,
      panelBg:getComputedStyle(document.querySelector('.mv-cell')).backgroundColor,
      muted:getComputedStyle(document.querySelector('.mv-cell em')).color},
  };
});
console.log(JSON.stringify(out, null, 1));
const cr = (a,b2)=>{const L1=rel(a),L2=rel(b2);const [hi,lo]=L1>L2?[L1,L2]:[L2,L1];return ((hi+.05)/(lo+.05)).toFixed(2)};
console.log("contrast hero/panel :", cr(out.colours.text, out.colours.panelBg));
console.log("contrast muted/panel:", cr(out.colours.muted, out.colours.panelBg));
console.log("errors:", errs.length, errs.slice(0,2).join(" | "));
for (const w of [375, 768, 1024, 1440]) {
  await pg.setViewportSize({ width: w, height: 1100 });
  await pg.waitForTimeout(1200);
  const o = await pg.evaluate(() => ({
    hscroll: document.documentElement.scrollWidth > window.innerWidth + 2,
    heroFs: getComputedStyle(document.querySelector('.mv-hero .v')).fontSize }));
  console.log(`  ${w}px  horizontal-scroll=${o.hscroll}  hero=${o.heroFs}`);
}
await pg.setViewportSize({ width: 1800, height: 1700 }); await pg.waitForTimeout(1500);
await pg.screenshot({ path: "promax.png", fullPage: false });
await b.close();
