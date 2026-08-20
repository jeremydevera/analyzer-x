import { chromium } from "playwright";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1400, height: 900 } });
await p.goto("http://localhost:8597", { waitUntil: "networkidle" });
await p.waitForTimeout(6000);
const info = await p.evaluate(() => {
  const el = document.querySelector('.st-key-book');
  const chain = [];
  let n = el;
  for (let i=0;i<4 && n;i++){ chain.push({ cls:(n.className||'').toString().slice(0,70),
      testid:n.getAttribute('data-testid'), h:Math.round(n.getBoundingClientRect().height),
      inline:n.getAttribute('style')||'', csh:getComputedStyle(n).height }); n = n.parentElement; }
  // which rule sets 220px?
  const rules = [];
  for (const sheet of document.styleSheets) {
    let rs; try { rs = sheet.cssRules; } catch(e){ continue; }
    for (const r of rs) { if (r.cssText && /height:\s*220px/.test(r.cssText)) rules.push(r.cssText.slice(0,160)); }
  }
  return { chain, rules };
});
console.log(JSON.stringify(info, null, 1));
// try forcing with a very specific !important rule injected at runtime
const forced = await p.evaluate(() => {
  const s = document.createElement('style');
  s.textContent = '.stVerticalBlock.st-key-book{height:430px !important;max-height:430px !important;}';
  document.head.appendChild(s);
  const el = document.querySelector('.st-key-book');
  return { h: Math.round(el.getBoundingClientRect().height), scrolls: el.scrollHeight > el.clientHeight };
});
console.log("forced via injected sheet:", JSON.stringify(forced));
await b.close();
