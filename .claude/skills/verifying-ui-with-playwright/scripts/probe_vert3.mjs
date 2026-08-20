import { chromium } from "playwright";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1400, height: 900 } });
await p.goto("http://localhost:8597", { waitUntil: "networkidle" });
await p.waitForTimeout(6000);
const res = await p.evaluate(() => {
  const s = document.createElement('style');
  s.textContent = `
    :root{ --ta-h-book: 430px; }
    [data-testid="stLayoutWrapper"]:has(> .st-key-book){
      height: var(--ta-h-book) !important;
      flex: 0 0 var(--ta-h-book) !important;
    }
    .stVerticalBlock.st-key-book{ height: var(--ta-h-book) !important; }`;
  document.head.appendChild(s);
  const el = document.querySelector('.st-key-book');
  const wrap = el.parentElement;
  return { pane: Math.round(el.getBoundingClientRect().height),
           wrapper: Math.round(wrap.getBoundingClientRect().height),
           scrolls: el.scrollHeight > el.clientHeight,
           overflow: getComputedStyle(el).overflowY };
});
console.log("with :has() on stLayoutWrapper ->", JSON.stringify(res));
// now drag it live via the var only
const dragged = await p.evaluate(() => {
  document.documentElement.style.setProperty('--ta-h-book','300px');
  const el = document.querySelector('.st-key-book');
  return Math.round(el.getBoundingClientRect().height);
});
console.log("live var drag to 300 ->", dragged);
await p.locator('button:has-text("rr")').first().click();
await p.waitForTimeout(2500);
const after = await p.evaluate(() => Math.round(document.querySelector('.st-key-book').getBoundingClientRect().height));
console.log("survives rerun ->", after);
await b.close();
