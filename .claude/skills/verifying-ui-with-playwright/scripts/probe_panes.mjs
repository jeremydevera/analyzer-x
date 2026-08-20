import { chromium } from "playwright";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1600, height: 1000 } });
await p.goto("http://localhost:8599", { waitUntil: "networkidle" });
await p.waitForTimeout(6000);

const w = async (key) => {
  const el = p.locator(`.st-key-${key}`).first();
  if (await el.count() === 0) return "MISSING";
  const bb = await el.boundingBox();
  return bb ? Math.round(bb.width) : "nobox";
};
console.log("PROBE1 per-widget width= (blanket caps active):");
for (const k of ["t72","t520","s132","n88","m190"]) console.log("  ", k, "=", await w(k), "px");

const bar = await p.locator(".st-key-bar").first().boundingBox();
const kids = await p.locator('.st-key-bar > div > div').count();
console.log("PROBE2 horizontal toolbar: box", bar && Math.round(bar.width)+"x"+Math.round(bar.height), "children", kids);
const inline = await p.evaluate(() => {
  const el = document.querySelector('.st-key-bar');
  if (!el) return "missing";
  const inner = el.querySelector('[data-testid="stHorizontalBlock"], div');
  return getComputedStyle(inner).flexDirection + " / display " + getComputedStyle(inner).display;
});
console.log("  inner flex:", inline);

const pane = await p.evaluate(() => {
  const el = document.querySelector('.st-key-pane');
  if (!el) return "missing";
  const sc = el.querySelector('*');
  const cands = [...el.querySelectorAll('*')].filter(n => n.scrollHeight > n.clientHeight + 20 && n.clientHeight > 50);
  return { h: Math.round(el.getBoundingClientRect().height),
           scrollers: cands.length,
           overflow: cands[0] ? getComputedStyle(cands[0]).overflowY : "none",
           scrollHeight: cands[0] ? cands[0].scrollHeight : 0 };
});
console.log("PROBE3 fixed-height container:", JSON.stringify(pane));

const js = await p.evaluate(() => {
  const d = document.getElementById('probe4');
  return { text: d ? d.textContent : "MISSING",
           attr: d ? d.getAttribute('data-js') : null,
           cssvar: document.documentElement.style.getPropertyValue('--ta-split'),
           hasClickHook: typeof window.__taClick };
});
console.log("PROBE4 st.html JS:", JSON.stringify(js));

if (js.hasClickHook === "function") {
  const ok = await p.evaluate(() => window.__taClick("PALETTE_TARGET"));
  await p.waitForTimeout(2500);
  const body = await p.innerText("body");
  console.log("  JS-driven button click returned", ok, "| clicked counter:", (body.match(/clicked:\s*(\d+)/)||[])[1]);
}
await p.keyboard.press("Meta+k");
await p.waitForTimeout(600);
const pal = await p.evaluate(() => {
  const d = document.getElementById('probe4');
  return { palette: d && d.getAttribute('data-palette'), keys: window.__taKeys };
});
console.log("  keydown capture:", JSON.stringify(pal));
await p.screenshot({ path: "probe_panes.png", fullPage: false });
await b.close();
