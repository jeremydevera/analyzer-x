import { chromium } from 'playwright';
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1680, height: 900 } });
p.on('dialog', d => d.dismiss());
await p.goto('http://localhost:8503/trade', { waitUntil: 'networkidle' });
await p.waitForTimeout(5000);
const el = p.locator('div.overflow-hidden').filter({ hasText: 'Strategies you have deployed' }).first();
await el.screenshot({ path: '/tmp/deployed-default.png' });
await b.close(); console.log('ok');
