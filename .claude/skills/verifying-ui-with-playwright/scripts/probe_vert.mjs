import { chromium } from "playwright";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1400, height: 900 } });
await p.goto("http://localhost:8597", { waitUntil: "networkidle" });
await p.waitForTimeout(6000);
const h = async () => await p.evaluate(() => {
  const el = document.querySelector('.st-key-book');
  return { box: Math.round(el.getBoundingClientRect().height),
           inlineStyle: el.getAttribute('style') || '(none)',
           computed: getComputedStyle(el).height,
           scrolls: el.scrollHeight > el.clientHeight };
});
console.log("default:", JSON.stringify(await h()));
await p.evaluate(() => document.documentElement.style.setProperty('--ta-h-book','430px'));
await p.waitForTimeout(300);
console.log("after JS drag to 430:", JSON.stringify(await h()));
await p.locator('button:has-text("rr")').first().click();
await p.waitForTimeout(2500);
console.log("after rerun:", JSON.stringify(await h()));
await b.close();
