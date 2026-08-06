// Screenshot a Streamlit page and report where named elements landed.
//
//   node verify.mjs <url> [tabName] [--find "text"]... [--wait ms]
//                   [--out file.png] [--dump-testids]
//
// Prints FOUND/NOT-FOUND lines with bounding boxes so the caller can check
// geometry (which column, above/below the fold) — presence alone is not
// verification.
import { chromium } from 'playwright';

const args = process.argv.slice(2);
const url = args[0] && !args[0].startsWith('--') ? args[0] : 'http://localhost:8503';
const tab = args[1] && !args[1].startsWith('--') ? args[1] : null;
const finds = [];
let wait = 8000, out = 'verify-ui.png', dumpTestids = false;
for (let i = 0; i < args.length; i++) {
  if (args[i] === '--find') finds.push(args[++i]);
  if (args[i] === '--wait') wait = parseInt(args[++i], 10);
  if (args[i] === '--out') out = args[++i];
  if (args[i] === '--dump-testids') dumpTestids = true;
}

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1680, height: 1050 } });
await page.goto(url, { waitUntil: 'networkidle' });
await page.waitForTimeout(wait);

if (tab) {
  const t = page.getByText(tab, { exact: true }).first();
  if (await t.count()) { await t.click(); await page.waitForTimeout(Math.min(wait, 5000)); }
}

await page.screenshot({ path: out, fullPage: true });
console.log('SCREENSHOT', out);

for (const text of finds) {
  const el = page.locator(`text=${text}`).first();
  if (await el.count()) {
    const box = await el.boundingBox();
    console.log('FOUND', JSON.stringify({ text, ...box }));
  } else {
    console.log('NOT-FOUND', text);
  }
}

if (dumpTestids) {
  const tids = await page.evaluate(() =>
    [...new Set([...document.querySelectorAll('[data-testid]')]
      .map(el => el.getAttribute('data-testid')))].sort());
  console.log('TESTIDS', JSON.stringify(tids));
}

await browser.close();
