import { chromium } from 'playwright';
const b = await chromium.launch();
for (const [p, f] of [['/trade','/tmp/final-trade.png'], ['/analysis','/tmp/final-analysis.png']]) {
  const pg = await b.newPage({ viewport: { width: 1680, height: 1150 } });
  pg.on('dialog', d => d.dismiss());
  await pg.goto('http://localhost:8503' + p, { waitUntil: 'networkidle' });
  await pg.waitForTimeout(5000);
  await pg.screenshot({ path: f });
  await pg.close();
}
await b.close(); console.log('shot');
