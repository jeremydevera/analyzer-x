import { chromium } from 'playwright-core';
const b = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' });
const ctx = await b.newContext({ viewport: { width: 1500, height: 1400 } });
await ctx.addInitScript(() => { try { localStorage.setItem('theme', 'dark'); } catch {} });
const p = await ctx.newPage();
await p.goto('http://127.0.0.1:8503/backtest', { waitUntil: 'domcontentloaded', timeout: 90000 });
await p.waitForTimeout(9000);
const card = p.locator('h3:has-text("Stored strategies")').first()
  .locator('xpath=ancestor::div[contains(@class,"rounded")][1]');
await card.locator('select[aria-label="Timeframe"]').selectOption('1h');
await card.locator('input[aria-label="Minimum trades"]').fill('100');
await card.locator('button:has-text("Apply")').first().click();
for (let i = 0; i < 60; i++) {
  await p.waitForTimeout(1000);
  if ((await card.locator('[aria-label^="remove filter"]').count()) >= 2) break;
}
await p.waitForTimeout(1000);
// contrast of the chip and the group label, resolved BY THE BROWSER
const probe = await p.evaluate(() => {
  const px = (c) => { const cv = document.createElement('canvas').getContext('2d');
    cv.fillStyle = c; cv.fillRect(0, 0, 1, 1); const d = cv.getImageData(0, 0, 1, 1).data;
    return [d[0], d[1], d[2]]; };
  const lum = (c) => { const [r, g, bb] = px(c).map(v => { v /= 255;
    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); });
    return 0.2126 * r + 0.7152 * g + 0.0722 * bb; };
  const ratio = (a, bg) => { const l1 = lum(a), l2 = lum(bg);
    return ((Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05)).toFixed(2); };
  const ground = (el) => { let n = el;
    while (n) { const c = getComputedStyle(n).backgroundColor;
      if (c && c !== 'rgba(0, 0, 0, 0)' && !/, 0\)$/.test(c)) return c; n = n.parentElement; }
    return 'rgb(255,255,255)'; };
  const out = [];
  const chip = document.querySelector('[aria-label^="remove filter"]')?.closest('span');
  if (chip) out.push({ what: 'chip', text: chip.innerText.trim(),
    color: getComputedStyle(chip).color, bg: ground(chip),
    ratio: ratio(getComputedStyle(chip).color, ground(chip)) });
  for (const s of document.querySelectorAll('span')) {
    if (/^(WHAT|HOW GOOD|WINDOW|ONE ROW)$/i.test(s.innerText.trim())) {
      out.push({ what: 'label ' + s.innerText.trim(), color: getComputedStyle(s).color,
        bg: ground(s), ratio: ratio(getComputedStyle(s).color, ground(s)) });
    }
  }
  const ph = document.querySelector('input[aria-label="Maximum stop loss percent"]');
  if (ph) out.push({ what: 'placeholder box', color: getComputedStyle(ph).color,
    bg: ground(ph), ratio: ratio(getComputedStyle(ph).color, ground(ph)) });
  return out;
});
console.log(JSON.stringify(probe, null, 1));
await p.locator('h3:has-text("Stored strategies")').first().scrollIntoViewIfNeeded();
await p.waitForTimeout(300);
const box = await card.boundingBox();
const sy = await p.evaluate(() => window.scrollY);
await p.screenshot({ path: 'dark_filters.png', fullPage: true,
  clip: { x: box.x, y: box.y + sy, width: box.width, height: 460 } });
await b.close();
