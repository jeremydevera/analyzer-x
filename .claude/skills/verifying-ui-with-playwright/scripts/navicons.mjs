import { chromium } from "playwright";
const b = await chromium.launch();
const p = await b.newPage({viewport:{width:1440,height:1000}});
await p.goto("http://localhost:8503/trade", {waitUntil:"domcontentloaded", timeout:90000});
await p.waitForTimeout(12000);
const items = await p.$$eval('aside a.menu-item, nav a.menu-item, a.menu-item', els =>
  els.map(a => {
    const svg = a.querySelector('svg');
    const r = svg ? svg.getBoundingClientRect() : null;
    // signature of the glyph geometry: path count + first path's d prefix
    const paths = svg ? [...svg.querySelectorAll('path,circle,rect')] : [];
    const sig = paths.map(n => (n.getAttribute('d')||n.tagName).slice(0,28)).join('|');
    return {
      label: (a.textContent||'').trim(),
      w: r ? +r.width.toFixed(1) : null,
      h: r ? +r.height.toFixed(1) : null,
      x: r ? +r.x.toFixed(1) : null,
      sig: sig.slice(0,60),
    };
  }));
console.log("rail items:", items.length);
for (const i of items) console.log(`  ${i.label.padEnd(12)} ${i.w}x${i.h} @x${i.x}  sig=${i.sig.slice(0,34)}`);
const sigs = items.map(i=>i.sig);
console.log("UNIQUE glyphs:", new Set(sigs).size, "of", sigs.length);
console.log("sizes all equal:", new Set(items.map(i=>`${i.w}x${i.h}`)).size === 1, [...new Set(items.map(i=>`${i.w}x${i.h}`))]);
console.log("x all equal:", new Set(items.map(i=>i.x)).size === 1);
const aside = await p.$('aside') || await p.$('nav');
if (aside) await aside.screenshot({path:"nav-icons.png"});
await b.close();
