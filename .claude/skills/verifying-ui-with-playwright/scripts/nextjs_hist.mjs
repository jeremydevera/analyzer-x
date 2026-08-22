import { chromium } from 'playwright';
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1680, height: 1050 } });
const errs = [];
p.on('console', m => { if (m.type() === 'error') errs.push(m.text().slice(0, 90)); });
await p.goto('http://localhost:8503/backtest', { waitUntil: 'domcontentloaded' });
await p.waitForTimeout(12000);
const t = await p.locator('body').innerText();
const i = t.search(/Trade ledger/i);
console.log('Trade ledger panel found:', i >= 0);
console.log('SEGMENT:', t.slice(i, i + 560).replace(/\n+/g, ' | '));
console.log('console errors:', errs.slice(0, 3));
const el = p.locator('text=/Trade ledger/i').first();
if (await el.count()) { await el.scrollIntoViewIfNeeded(); await p.waitForTimeout(1500); }
await p.screenshot({ path: '/tmp/nextjs_hist.png' });
await b.close();
