import { chromium } from "playwright";
const b = await chromium.launch();
const p = await b.newPage({viewport:{width:1440,height:1000}});
await p.goto("http://localhost:8503/backtest", {waitUntil:"domcontentloaded", timeout:90000});
await p.waitForTimeout(12000);
const colors = await p.$$eval('a.menu-item', els => els.map(a => {
  const svg = a.querySelector('svg');
  return { label:(a.textContent||'').trim(),
           color: svg ? getComputedStyle(svg).color : null,
           active: a.className.includes('menu-item-active') };
}));
for (const c of colors) console.log(`  ${c.label.padEnd(12)} active=${String(c.active).padEnd(5)} color=${c.color}`);
const act = colors.filter(c=>c.active), ina = colors.filter(c=>!c.active);
console.log("active glyph recolors:", act.length===1 && act[0].color !== ina[0].color, "|", act[0]?.color, "vs", ina[0]?.color);
const rail = await p.$('aside');
await rail.screenshot({path:"nav-icons.png"});
await b.close();
