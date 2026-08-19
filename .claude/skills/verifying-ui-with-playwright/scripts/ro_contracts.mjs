import { chromium } from "playwright";
const b = await chromium.launch();
const pg = await b.newPage({ viewport: { width: 1800, height: 1400 } });
const errs = [];
pg.on("pageerror", e => errs.push(String(e)));
await pg.goto("http://localhost:8503", { waitUntil: "networkidle" });
await pg.waitForTimeout(9000);
await pg.locator('[data-testid="stRadio"] label').filter({ hasText: /^Auto Trade$/ }).first().click();
await pg.waitForTimeout(9000);

// every text input still on the page, by its aria-label
const labels = await pg.locator('[data-testid="stTextInput"] input')
  .evaluateAll(ns => ns.map(n => n.getAttribute("aria-label") || n.placeholder || "?"));
console.log("text inputs :", JSON.stringify(labels));
console.log("contracts editable:", labels.some(l => /contract/i.test(l)) ? "YES — BAD" : "no");

// the strategy grid, read back as rendered text
const grid = pg.locator('[data-testid="stVerticalBlock"]').filter({ hasText: /CONTRACTS/i }).last();
const txt = await grid.innerText().catch(() => "");
const rows = txt.split("\n").filter(Boolean);
console.log("---- grid text ----");
console.log(rows.slice(0, 60).join("\n"));
console.log("exceptions  :", errs.length, errs.slice(0,3).join(" | "));
await pg.screenshot({ path: "ro-contracts.png", fullPage: false });
await b.close();
