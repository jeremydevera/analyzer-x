import { chromium } from "playwright";
const b = await chromium.launch();
const pg = await b.newPage({ viewport: { width: 1800, height: 1200 } });
await pg.goto("http://localhost:8503", { waitUntil: "networkidle" });
await pg.waitForTimeout(12000);
const out = await pg.evaluate(() => {
  const s = document.querySelector('[data-testid="stSidebar"]');
  // which rule wins on display?
  const hits = [];
  for (const sheet of document.styleSheets) {
    let rules; try { rules = sheet.cssRules; } catch { continue; }
    for (const r of rules || []) {
      if (!r.selectorText || !r.style || !r.style.display) continue;
      try { if (s.matches(r.selectorText) && r.style.display === "none")
        hits.push({sel:r.selectorText.slice(0,120), pri:r.style.getPropertyPriority("display"),
                   href:(sheet.href||"inline").slice(-40)}); } catch {}
    }
  }
  return { hits, parentDisplay: getComputedStyle(s.parentElement).display,
           parentTag: s.parentElement.tagName + "." + (s.parentElement.className||"").slice(0,40),
           inlineStyle: s.getAttribute("style") };
});
console.log(JSON.stringify(out, null, 1));
await b.close();
