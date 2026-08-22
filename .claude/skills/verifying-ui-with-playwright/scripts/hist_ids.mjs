import { chromium } from 'playwright';
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1920, height: 1050 } });
await p.goto('http://localhost:8507', { waitUntil: 'networkidle' });
await p.waitForTimeout(7000);
await p.locator('text=Auto Trade').first().click();
await p.waitForTimeout(30000);
const t = await p.locator('body').innerText();
const i = t.search(/TRADE HISTORY/i);
console.log('history found:', i >= 0);
const seg = t.slice(i, i + 900).replace(/\n+/g, ' | ');
console.log('SEGMENT:', seg.slice(0, 620));
const el = p.locator('text=/trade history/i').first();
if (await el.count()) { await el.scrollIntoViewIfNeeded(); await p.waitForTimeout(1200); }
await p.screenshot({ path: '/tmp/hist_ids.png' });
await b.close();
