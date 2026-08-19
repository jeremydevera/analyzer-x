import { chromium } from "playwright";
const b = await chromium.launch();
const pg = await b.newPage({ viewport: { width: 1800, height: 1400 } });
const errs = []; pg.on("pageerror", e => errs.push(String(e)));
await pg.goto("http://localhost:8503", { waitUntil: "networkidle" });
await pg.waitForTimeout(9000);
const R = () => pg.locator('[data-testid="stHorizontalBlock"]').filter({ hasText: /1 YEAR/ });
for (let a = 0; a < 4; a++) {
  await pg.locator('[data-testid="stRadio"] label').filter({ hasText: /^Auto Trade$/ }).first().click({ force: true });
  await pg.waitForTimeout(9000);
  if (await R().count()) break;
}
const night = pg.locator('input[aria-label="Night mode"]');
const nightBox = pg.locator('label').filter({ hasText: /Night mode/i }).first();
const isNight = async () => await night.isChecked();
console.log("night mode on load:", await isNight());

const probe = async (tag) => {
  // the computed ground + ink of a section, and of the page behind it
  const v = await pg.evaluate(() => {
    const sec = document.querySelector('[class*="st-key-tmsec_"]');
    const app = document.querySelector('[data-testid="stAppViewContainer"]');
    const cs = getComputedStyle(sec), ca = getComputedStyle(app);
    const tile = document.querySelector('.tm-rib > div');
    return {
      sectionBg: cs.backgroundColor, sectionBorder: cs.borderTopWidth + " " + cs.borderTopColor,
      sectionColor: cs.color, appBg: ca.backgroundColor,
      tileBg: tile ? getComputedStyle(tile).backgroundColor : "(none)",
      radius: cs.borderRadius,
    };
  });
  console.log(`${tag}  app=${v.appBg}  section=${v.sectionBg} radius=${v.radius} borderTop=${v.sectionBorder}`);
  console.log(`${tag}  ink=${v.sectionColor}  tile=${v.tileBg}`);
};
await probe(await isNight() ? "NIGHT " : "LIGHT ");
await pg.screenshot({ path: `ui-${await isNight() ? "night" : "light"}.png`, fullPage: false });

await nightBox.click({ force: true });
await pg.waitForTimeout(9000);
if (!(await R().count())) {
  for (let a = 0; a < 3; a++) {
    await pg.locator('[data-testid="stRadio"] label').filter({ hasText: /^Auto Trade$/ }).first().click({ force: true });
    await pg.waitForTimeout(8000);
    if (await R().count()) break;
  }
}
await probe(await isNight() ? "NIGHT " : "LIGHT ");
await pg.screenshot({ path: `ui-${await isNight() ? "night" : "light"}.png`, fullPage: false });
console.log("errors:", errs.length, errs.slice(0,2).join(" | "));
await b.close();
