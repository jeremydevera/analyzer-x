/**
 * watch_ui.mjs — walk the real screens like a person and collect what breaks.
 *
 * Launches the Chrome already on this machine through playwright-core, so it
 * does NOT need the Playwright MCP server (which times out on this box) and
 * cannot collide with the mcp-chrome profile an orphaned browser holds.
 *
 *   node watch_ui.mjs [--ui http://127.0.0.1:8503] [--api http://127.0.0.1:8787]
 *                     [--out findings.json] [--shots] [--pages backtest,trade]
 *
 * It reports ONLY things a person would call wrong:
 *   - an uncaught page error or a console error
 *   - a request that failed or answered 4xx/5xx
 *   - Next's "Application error: a client-side exception" screen
 *   - a page that renders no content at all
 *   - a backend traceback written while the walk was running
 * Everything else is noise and is deliberately not collected.
 */
import { chromium } from "playwright-core";
import { readFileSync, writeFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";

const arg = (k, d) => {
  const i = process.argv.indexOf(`--${k}`);
  return i > -1 && process.argv[i + 1] && !process.argv[i + 1].startsWith("--")
    ? process.argv[i + 1] : d;
};
const has = (k) => process.argv.includes(`--${k}`);

const UI = arg("ui", "http://127.0.0.1:8503");
const API = arg("api", "http://127.0.0.1:8787");
const OUT = arg("out", "findings.json");
const PAGES = arg("pages", "backtest,trade,candles,analysis,models,new-crypto")
  .split(",").map((s) => s.trim()).filter(Boolean);
const CHROME = arg("chrome",
  "C:/Program Files/Google/Chrome/Application/chrome.exe");

// Backend logs to read AFTER the walk, from the byte offset they held BEFORE
// it — so a traceback from last week is not reported as something we caused.
const LOGDIR = join(homedir(), ".tradingagents");
const LOGS = ["api.log", "auto_trade.log", "rows_index.log",
              "db_backtest.log", "db_download.log", "db_collect.log"];

const sizeOf = (p) => { try { return statSync(p).size; } catch { return 0; } };
const tailFrom = (p, from) => {
  try {
    const buf = readFileSync(p);
    return buf.length > from ? buf.subarray(from).toString("utf8", 0, 400000) : "";
  } catch { return ""; }
};

const findings = [];
const add = (f) => {
  // one row per distinct problem: the same console error on six pages is one
  // finding with six pages, not six findings nobody will read
  const key = `${f.kind}|${f.where}|${(f.detail || "").slice(0, 200)}`;
  const seen = findings.find((x) => x.key === key);
  if (seen) { if (!seen.pages.includes(f.page)) seen.pages.push(f.page); return; }
  findings.push({ key, kind: f.kind, where: f.where, detail: f.detail,
                  pages: [f.page], at: new Date().toISOString() });
};

const before = Object.fromEntries(LOGS.map((n) => [n, sizeOf(join(LOGDIR, n))]));

const browser = await chromium.launch({ executablePath: CHROME });
const ctx = await browser.newContext({ viewport: { width: 1600, height: 1100 } });
const page = await ctx.newPage();

page.on("pageerror", (e) =>
  add({ kind: "page-error", where: "browser", detail: String(e.message || e),
        page: page.url() }));
page.on("console", (m) => {
  if (m.type() !== "error") return;
  add({ kind: "console-error", where: "browser", detail: m.text().slice(0, 500),
        page: page.url() });
});
page.on("requestfailed", (r) =>
  add({ kind: "request-failed", where: r.url().replace(UI, "").replace(API, ""),
        detail: r.failure()?.errorText || "failed", page: page.url() }));
page.on("response", (r) => {
  if (r.status() < 400) return;
  add({ kind: `http-${r.status()}`,
        where: r.url().replace(UI, "").replace(API, ""),
        detail: r.request().method(), page: page.url() });
});

const walked = [];
for (const name of PAGES) {
  const url = `${UI}/${name}`;
  try {
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 90000 });
    // long enough for the panels' own fetches to land and fail
    await page.waitForTimeout(Number(arg("settle", "12000")));
    const body = await page.evaluate(() => document.body.innerText || "");
    if (/Application error|client-side exception/i.test(body))
      add({ kind: "app-crash", where: name,
            detail: body.slice(0, 300).replace(/\s+/g, " "), page: url });
    if (body.trim().length < 40)
      add({ kind: "blank-page", where: name,
            detail: `rendered ${body.trim().length} characters`, page: url });
    walked.push({ page: name, chars: body.trim().length });
    if (has("shots"))
      await page.screenshot({ path: `shot-${name}.png`, fullPage: false });
  } catch (e) {
    add({ kind: "navigation-failed", where: name,
          detail: String(e.message || e).slice(0, 300), page: url });
    walked.push({ page: name, chars: 0 });
  }
}
await browser.close();

// BACKEND, from the offset held before the walk
for (const n of LOGS) {
  const text = tailFrom(join(LOGDIR, n), before[n]);
  if (!text) continue;
  const lines = text.split(/\r?\n/);
  lines.forEach((ln, i) => {
    if (!/Traceback \(most recent call last\)|^\s*\w+Error:|CRITICAL|ERROR:/.test(ln))
      return;
    add({ kind: "backend-error", where: n,
          detail: lines.slice(i, i + 4).join(" | ").slice(0, 400), page: "(server)" });
  });
}

const report = {
  ran: new Date().toISOString(), ui: UI, api: API,
  walked, findings: findings.map(({ key, ...f }) => f),
};
writeFileSync(OUT, JSON.stringify(report, null, 2));
console.log(`walked ${walked.length} page(s): ` +
  walked.map((w) => `${w.page}(${w.chars})`).join(" "));
console.log(`findings: ${findings.length} -> ${OUT}`);
for (const f of report.findings)
  console.log(`  [${f.kind}] ${f.where} :: ${(f.detail || "").slice(0, 120)}` +
              `   (${f.pages.length} page(s))`);
process.exit(findings.length ? 1 : 0);
