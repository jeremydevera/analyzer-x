import { chromium } from "playwright";
const b = await chromium.launch();
const p = await b.newPage({viewport:{width:1440,height:1000}, colorScheme:'dark'});
await p.addInitScript(() => { try { localStorage.setItem('theme','dark'); } catch(e){} });
await p.goto("http://localhost:8503/trade", {waitUntil:"domcontentloaded", timeout:90000});
await p.waitForTimeout(12000);
const dark = await p.evaluate(() => document.documentElement.classList.contains('dark'));
console.log("dark class on <html>:", dark);
const info = await p.$$eval('a.menu-item', els => els.map(a => {
  const svg = a.querySelector('svg');
  const r = svg.getBoundingClientRect();
  return { label:(a.textContent||'').trim(), color: getComputedStyle(svg).color,
           box:`${r.width.toFixed(0)}x${r.height.toFixed(0)}`,
           active: a.className.includes('menu-item-active') };
}));
for (const c of info) console.log(`  ${c.label.padEnd(12)} ${c.box} active=${String(c.active).padEnd(5)} ${c.color}`);
const rail = await p.$('aside');
await rail.screenshot({path:"nav-icons-dark.png"});
await b.close();
