import { chromium } from "playwright";
const b = await chromium.launch();
const pg = await b.newPage({ viewport: { width: 1800, height: 1200 } });
await pg.goto("http://localhost:8503", { waitUntil: "networkidle" });
await pg.waitForTimeout(12000);
const out = await pg.evaluate(() => {
  const s = document.querySelector('[data-testid="stSidebar"]');
  if (!s) return { none: true };
  const r = s.getBoundingClientRect(), cs = getComputedStyle(s);
  const collapsed = document.querySelector('[data-testid="stSidebarCollapsedControl"], [data-testid="collapsedControl"]');
  return { w: Math.round(r.width), h: Math.round(r.height), x: Math.round(r.x),
    display: cs.display, visibility: cs.visibility, transform: cs.transform,
    ariaExpanded: s.getAttribute("aria-expanded"),
    collapsedControl: !!collapsed,
    firstBtn: (() => { const btn=[...s.querySelectorAll("button")].find(x=>/Auto Trade/.test(x.innerText));
      if(!btn) return null; const br=btn.getBoundingClientRect();
      return {w:Math.round(br.width),h:Math.round(br.height),x:Math.round(br.x),
              vis:getComputedStyle(btn).visibility}; })() };
});
console.log(JSON.stringify(out, null, 1));
await pg.screenshot({ path: "side-probe.png", fullPage: false });
await b.close();
