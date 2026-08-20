import { chromium } from "playwright";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1600, height: 1000 } });
await p.goto("http://localhost:8598", { waitUntil: "networkidle" });
await p.waitForTimeout(6000);

// A: does the fixed-height container really scroll independently?
const scr = await p.evaluate(() => {
  const el = document.querySelector('.st-key-scr');
  const walk = [el, ...el.querySelectorAll('*')];
  const s = walk.find(n => n.scrollHeight > n.clientHeight + 30);
  if (!s) return { found: false };
  const before = s.scrollTop; s.scrollTop = 400;
  return { found: true, tag: s.tagName, cls: (s.className||'').slice(0,60),
           overflowY: getComputedStyle(s).overflowY,
           clientH: s.clientHeight, scrollH: s.scrollHeight,
           scrolledFrom: before, scrolledTo: s.scrollTop };
});
console.log("A scroll pane:", JSON.stringify(scr));

// B: CSS-var-driven split — measure, then have JS change the var, measure again
const meas = async () => await p.evaluate(() => {
  const cols = document.querySelectorAll('.st-key-split [data-testid="stColumn"]');
  return [...cols].map(c => Math.round(c.getBoundingClientRect().width));
});
console.log("B split default:", JSON.stringify(await meas()));
await p.evaluate(() => { localStorage.setItem('ta_split','2.4fr');
  document.documentElement.style.setProperty('--ta-split','2.4fr'); });
await p.waitForTimeout(400);
console.log("B split after JS drag to 2.4fr:", JSON.stringify(await meas()));

// C: does the st.html script re-execute after a rerun (so it can re-apply state)?
console.log("C before rerun:", await p.locator("#p2").innerText());
await p.locator('button:has-text("RERUN_ME")').first().click();
await p.waitForTimeout(3000);
console.log("C after rerun :", await p.locator("#p2").innerText());
console.log("C split survived rerun:", JSON.stringify(await meas()));
console.log("C runs counter:", (await p.innerText("body")).match(/script runs this session:\s*(\d+)/)?.[1]);

// D: sticky header + sortable table alternative: st.dataframe row-select
await p.screenshot({ path: "probe_panes2.png" });
await b.close();
