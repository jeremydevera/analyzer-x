#!/usr/bin/env node
// practice_backtest_audit: practice trades against their stored backtests,
// through the real screens. Read only. See ../SKILL.md for the operator's own
// twelve steps (Oct 14, 2026) and the design they approved.
import { chromium } from "playwright-core";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { accuracyLines, compare, dailyAccuracy, fmtWhen, fromReplay, idAnswer, money, nextSaved, parseWhen,
         pastDays, split, tradeKey } from "./match.mjs";

const argv = process.argv.slice(2);
const arg = (name, def) => {
  const i = argv.indexOf(`--${name}`);
  return i >= 0 && i + 1 < argv.length ? argv[i + 1] : def;
};
const flag = (name) => argv.includes(`--${name}`);

const BASE = arg("base", "http://localhost:8503");
// the back end itself for the stored-backtest replay: the page's /api proxy
// gives up at 30 s, and one replay measured 12-26 s (Oct 17, 2026)
const API = arg("api", "http://localhost:8787");
const CHROME = arg("chrome", "C:/Program Files/Google/Chrome/Application/chrome.exe");
const OPEN_TOL_MIN = Number(arg("open-tolerance", "10"));
const HOME = join(homedir(), ".tradingagents", "practice_backtest_audit");
const STATE = join(HOME, "state.json");
// The move to Gate: every id before it was measured on MEXC and cannot match.
// The trades the move itself closed in that minute (`VENUE_SWITCH`) are named
// by match.mjs's split(), never compared.
const FIRST_RUN_FROM = "Oct 10, 2026 3:59am";

// ---------------------------------------------------------------- window
function readState() {
  try { return JSON.parse(readFileSync(STATE, "utf8")); } catch { return {}; }
}

function windowOf() {
  const now = Date.now();
  const day = arg("day");
  if (day) {
    const base = day === "yesterday"
      ? (() => { const d = new Date(); d.setHours(0, 0, 0, 0); return d.getTime() - 86_400_000; })()
      : day === "today"
        ? (() => { const d = new Date(); d.setHours(0, 0, 0, 0); return d.getTime(); })()
        : parseWhen(day);
    if (base == null) throw new Error(`--day ${day}: write it like "Oct 13, 2026", "yesterday" or "today"`);
    const next = new Date(base); next.setDate(next.getDate() + 1);
    return { since: base, until: next.getTime(), why: `trades closed on ${fmtWhen(base).slice(0, 12)}` };
  }
  // "the past N days" (operator, Oct 18, 2026): today and the days before it
  if (arg("days")) {
    const n = Number(arg("days"));
    if (!Number.isInteger(n) || n < 1) throw new Error(`--days ${arg("days")}: a whole number of days, 1 or more`);
    const { since, until } = pastDays(n, now);
    return { since, until, why: `trades closed in the past ${n} day(s), today included` };
  }
  if (arg("since")) {
    const since = parseWhen(arg("since"));
    const until = arg("until") ? parseWhen(arg("until")) : now;
    if (since == null || until == null) throw new Error("--since/--until: write them like \"Oct 12, 2026 12:00am\"");
    return { since, until, why: `trades closed from ${fmtWhen(since)} to ${fmtWhen(until)}` };
  }
  const st = readState();
  if (st.last_closed_ms) {
    return { since: st.last_closed_ms + 60_000, until: now,
             why: `trades closed since the last run's newest (${st.last_closed})` };
  }
  return { since: parseWhen(FIRST_RUN_FROM), until: now,
           why: `first run: trades closed since the move to Gate (${FIRST_RUN_FROM})` };
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitFor(fn, ms, every = 500) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    const v = await fn().catch(() => null);
    if (v) return v;
    await sleep(every);
  }
  return null;
}

// ------------------------------------------------- steps 1-3: practice list
async function collect(page, since, until) {
  await page.goto(`${BASE}/trade`, { waitUntil: "domcontentloaded", timeout: 120_000 });
  const mainTab = page.getByRole("tab", { name: "Main", exact: true });
  await mainTab.waitFor({ timeout: 120_000 });
  await mainTab.click();
  const demo = page.getByRole("button", { name: "DEMO — simulated" });
  await demo.waitFor({ timeout: 120_000 });
  await demo.click();
  const table = page.locator("table", { hasText: "running $" }).first();
  const seen = new Set();
  const trades = [];
  let examined = 0;
  for (;;) {
    const ok = await waitFor(async () => (await table.locator("tbody tr").count()) > 0, 90_000);
    if (!ok) throw new Error("the Main tab's DEMO list did not load within 90 s");
    await sleep(800);   // let one page finish drawing
    let older = false;
    for (const r of await table.locator("tbody tr").all()) {
      const cells = (await r.locator("td").allInnerTexts()).map((s) => s.trim());
      if (cells.length < 10) continue;          // the empty-state row
      // Main tab: room, id, opened, closed, held, coin, side, strategy,
      // closed by, PROFIT $, running $
      const [room, tradeId, opened, closed, held, coin, side, strategy, why, profit] = cells;
      examined += 1;
      const c = parseWhen(closed);
      if (c != null && c < since) { older = true; continue; }
      if (c != null && c >= until) continue;
      const key = tradeKey({ room, trade_id: tradeId, closed });
      if (seen.has(key)) continue;              // the list refreshes while it is read
      seen.add(key);
      trades.push({
        room, trade_id: tradeId.replace(/^#/, ""),
        strategy_id: (/#([A-Z0-9]{8})/.exec(strategy) || [])[1] || null,
        strategy: strategy.replace(/#[A-Z0-9]{8}/, "").trim(), coin, side,
        opened, closed, held, profit: money(profit), closed_by: why,
        opened_ms: parseWhen(opened), closed_ms: c,
      });
    }
    if (older) break;
    const info = await page.getByText(/page \d+ of \d+ · 5 per page/).first().textContent().catch(() => "");
    const m = /page (\d+) of (\d+)/.exec(info || "");
    if (!m || Number(m[1]) >= Number(m[2])) break;
    const before = await table.locator("tbody tr").first().innerText().catch(() => "");
    await page.getByRole("button", { name: "older", exact: true }).click();
    await waitFor(async () => (await table.locator("tbody tr").first().innerText()) !== before, 60_000);
  }
  return { trades, examined };
}

// ------------------------------------- a strategy the Backtest list hides
// NOT ON THE LIST IS NOT "NOT MEASURED" (operator, Oct 17, 2026: "What is the
// most accurate fix for this", then "yes"). Since Oct 16, 2026 8:44pm the list
// keeps only strategies whose win pays two losses after fees, but every stored
// row stays in its file and a row's trade log is built from the file: the
// server finds the row whose own settings make the id and runs the replay a
// click on it would run (/api/v2/strategies/trades-by-id, read only).
const TF_OF_KEY = /_(15m|30m|1h|4h|1d)(?:_|$)/;
async function storedLog(id, sample) {
  const coin = String(sample?.coin || "").trim();
  if (!coin) return { why: "its coin is not on the practice row" };
  const tf = TF_OF_KEY.exec(String(sample?.strategy || ""))?.[1];
  const q = new URLSearchParams({ row_id: id, coin, ...(tf ? { tf } : {}) });
  try {
    const r = await fetch(`${API}/api/v2/strategies/trades-by-id?${q}`,
                          { signal: AbortSignal.timeout(300_000) });
    if (!r.ok) return { why: `its stored backtest answered HTTP ${r.status}` };
    const d = await r.json();
    // no stored row makes the id: settled, never asked again by the next run
    if (!d.found) return { why: d.why || "no stored row makes this id", none: true };
    // a replay that could not run says why (no candles, ...): not checked
    if (!(d.log || []).length && d.why) return { why: d.why };
    return { log: fromReplay(d.log), row: d.row };
  } catch (e) {
    return { why: `its stored backtest did not answer (${String(e?.message || e).slice(0, 120)})` };
  }
}

// --------------------------------------------- steps 4-11: Stored strategies
async function lookup(page, id, sample) {
  const opener = page.locator('button[title^="every filter"]').first();
  await opener.waitFor({ timeout: 120_000 });
  await opener.click();
  const dlg = page.getByRole("dialog", { name: "Filters" });
  await dlg.waitFor({ timeout: 30_000 });
  const tp = dlg.getByLabel("Only rows whose take profit is equal to or wider than their stop loss");
  if (await tp.isChecked()) await tp.uncheck();
  await dlg.getByLabel("Row id").fill(id);
  // "Apply filters" is the button's label only when nothing is pending; with
  // the id typed it reads "Apply 2 filters", and while Stored strategies is
  // still answering its previous search it reads "searching 30s", disabled
  // (the first run, Oct 14, 2026, clicked during the page's opening search
  // and timed out). Its title never changes, so it is found by that and
  // clicked once the list is free.
  const apply = dlg.locator('button[title="send the boxes to the store"]');
  const ready = await waitFor(async () => (await apply.count()) > 0 && (await apply.isEnabled()), 600_000, 1000);
  if (!ready) throw new Error("the Apply button stayed busy for 10 minutes (Stored strategies still searching)");
  await apply.click();
  await dlg.waitFor({ state: "hidden", timeout: 30_000 }).catch(() => {});
  await sleep(1500);                     // let the new search start
  const res = await waitFor(async () => {
    const row = page.locator("tbody tr", { hasText: `#${id}` }).first();
    if ((await row.count()) && (await row.isVisible())) return { row };
    // still answering: "loading row #ID - ... the figures above are still
    // the previous answer" (the second run, Oct 14, 2026, read that line as
    // a no-result and stopped looking)
    const loading = page.getByText(`loading row #${id}`).first();
    if ((await loading.count()) && (await loading.isVisible())) return null;
    // the panel's own no-result answers for an id, drawn only once the
    // search has finished with no row: "no row #ID in the store ..." or
    // the app's explanation of that id (StrategiesPanel, `rowIdWhy`)
    const warn = page.locator("p.pt-2.text-warning-600").first();
    if ((await warn.count()) && (await warn.isVisible())) {
      const t = await warn.innerText();
      // this id's answer when it names this id; the room it names is not a
      // leftover (match.mjs idAnswer, Oct 17, 2026)
      const why = idAnswer(t, id);
      return why ? { why } : null;
    }
    return null;
  }, 180_000);
  if (!res) return { found: false, why: "Stored strategies did not answer within 3 minutes" };
  if (res.why) {
    const listSaid = res.why.replace(/\s+/g, " ").slice(0, 300);
    const direct = await storedLog(id, sample);
    if (direct.log) return { found: true, log: direct.log, hidden: listSaid, row: direct.row };
    return { found: false, none: !!direct.none, why: `${listSaid} — and ${direct.why}` };
  }
  await res.row.click();
  const log = page.locator("table", { hasText: "closed by" }).filter({ hasText: "pnl $" }).last();
  const loaded = async () => (await log.count()) && (await log.locator("tbody tr").count()) > 0;
  let got = await waitFor(loaded, 120_000);
  if (!got) {
    // ONE more ask: a request that died while the site restarted is asked
    // again (the third run, Oct 14, 2026: two lists never drew while the
    // same lists answered in 1 s and 8 s when asked directly)
    await res.row.click().catch(() => {});
    got = await waitFor(loaded, 120_000);
  }
  if (!got) {
    const shot = `${base} no trade list ${id}.png`;
    await page.screenshot({ path: shot, fullPage: true }).catch(() => {});
    const said = await page.locator("p.text-theme-sm.text-gray-500").last().innerText().catch(() => "");
    return { found: true, log: null, screenshot: shot,
             why: `its trade list did not load${said ? `: ${said.replace(/\s+/g, " ").slice(0, 200)}` : ""}` };
  }
  const out = [];
  for (const r of await log.locator("tbody tr").all()) {
    const c = (await r.locator("td").allInnerTexts()).map((s) => s.trim());
    if (c.length < 12) continue;
    // opened, closed, held, side, closed by, entry, exit, rung, margin $,
    // funding $, W/L, pnl $, running $
    out.push({ opened: c[0], closed: c[1], held: c[2], side: c[3], closed_by: c[4],
               pnl: money(c[11]), opened_ms: parseWhen(c[0]), closed_ms: parseWhen(c[1]) });
  }
  return { found: true, log: out };
}

// ------------------------------------------------------------------- run
// (step 12, the match itself, is match.mjs's compare)
const win = windowOf();
const started = Date.now();
const day = new Date(started);
const runDir = join(HOME, "runs",
  `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(day.getDate()).padStart(2, "0")}`);
mkdirSync(runDir, { recursive: true });
// "Oct 14, 2026 1:40pm" -> "1-40pm" (a colon is illegal in a Windows name)
const stamp = fmtWhen(started).slice(13).replace(":", "-");
const base = join(runDir, `${stamp} audit`);
if (!existsSync(CHROME)) throw new Error(`Chrome not found at ${CHROME} (pass --chrome)`);

const browser = await chromium.launch({ executablePath: CHROME, headless: !flag("headed") });
const report = { window: { since: fmtWhen(win.since), until: fmtWhen(win.until), why: win.why },
                 started: fmtWhen(started), trades: [], ids: {}, failures: [] };
try {
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 1100 } });
  const page = await ctx.newPage();
  console.log(`[audit] ${win.why}: ${fmtWhen(win.since)} to ${fmtWhen(win.until)}`);
  const { trades, examined } = await collect(page, win.since, win.until);
  report.examined = examined;
  console.log(`[audit] ${trades.length} practice trade(s) in the window (${examined} rows read on the Main tab's DEMO list)`);
  const { compared, named, ids } = split(trades);
  if (named.length) {
    const why = {};
    for (const t of named) why[t.verdict] = (why[t.verdict] || 0) + 1;
    console.log(`[audit] ${named.length} not compared: ${Object.entries(why).map(([k, v]) => `${v} ${k}`).join("; ")}`);
  }
  console.log(`[audit] ${ids.length} strategy id(s) to look up: ${ids.join(", ")}`);
  if (ids.length) {
    await page.goto(`${BASE}/backtest-v2`, { waitUntil: "domcontentloaded", timeout: 120_000 });
    await page.getByText("Stored strategies").first().waitFor({ timeout: 120_000 });
  }
  for (const [n, id] of ids.entries()) {
    try {
      const got = await lookup(page, id, compared.find((x) => x.strategy_id === id));
      report.ids[id] = { found: got.found, why: got.why || "", trades: got.log ? got.log.length : null,
                         ...(got.hidden ? { not_on_list: got.hidden, row: got.row } : {}),
                         ...(got.screenshot ? { screenshot: got.screenshot } : {}) };
      console.log(`[audit] ${n + 1}/${ids.length} #${id}: ${!got.found ? `no result: ${got.why}`
        : got.log ? `${got.log.length} backtest trade(s)${got.hidden ? " (not on the list: read from its stored backtest)" : ""}`
          : `NOT CHECKED: ${got.why}`}`);
      for (const t of compared.filter((x) => x.strategy_id === id)) {
        const r = !got.found ? { verdict: got.none ? "no stored backtest makes this id" : "id not in Stored strategies",
                                 note: got.why }
          : got.log ? compare(t, got.log, OPEN_TOL_MIN)
            : { verdict: "not checked (its trade list did not load)", note: got.why };
        if (got.hidden && got.log) {
          // every such line says where its backtest came from
          r.source = "stored backtest";
          r.note = `not on the Backtest list — compared from its stored backtest${r.note ? `; ${r.note}` : ""}`;
        }
        report.trades.push({ ...t, ...r });
      }
    } catch (e) {
      const shot = `${base} fail ${id}.png`;
      await page.screenshot({ path: shot, fullPage: true }).catch(() => {});
      report.failures.push({ id, error: String(e).slice(0, 300), screenshot: shot });
      report.ids[id] = { found: null, why: `failed: ${String(e).slice(0, 160)}` };
      for (const t of compared.filter((x) => x.strategy_id === id)) report.trades.push({ ...t, verdict: "not checked (the step failed)" });
      console.log(`[audit] ${n + 1}/${ids.length} #${id}: FAILED ${String(e).slice(0, 160)} (screenshot ${shot})`);
      await page.goto(`${BASE}/backtest-v2`, { waitUntil: "domcontentloaded", timeout: 120_000 }).catch(() => {});
    }
  }
  report.trades.push(...named);
} finally {
  await browser.close().catch(() => {});
}

// ---------------------------------------------------------------- outputs
const counts = {};
// the strategies the list hides, counted apart, so the two can be compared
const counts_not_on_list = {};
for (const t of report.trades) {
  counts[t.verdict] = (counts[t.verdict] || 0) + 1;
  if (t.source === "stored backtest") counts_not_on_list[t.verdict] = (counts_not_on_list[t.verdict] || 0) + 1;
}
report.counts = counts;
report.counts_not_on_list = counts_not_on_list;
// the accuracy of each day of the window, on every run (Oct 18, 2026)
report.daily = dailyAccuracy(report.trades, win.since, win.until);
report.finished = fmtWhen(Date.now());
writeFileSync(`${base}.json`, JSON.stringify(report, null, 2));
const cols = ["room", "trade_id", "strategy_id", "strategy", "coin", "side", "opened", "closed", "held",
              "profit", "backtest_opened", "backtest_closed", "backtest_held", "backtest_profit",
              "opened_gap_min", "closed_gap_min", "difference", "verdict", "source", "note"];
const q = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
const lines = [cols.join(",")].concat(report.trades.map((t) => [
  t.room, t.trade_id, t.strategy_id, t.strategy, t.coin, t.side, t.opened, t.closed, t.held, t.profit,
  t.backtest?.opened, t.backtest?.closed, t.backtest?.held, t.backtest?.pnl,
  t.opened_gap_min, t.closed_gap_min, t.difference, t.verdict, t.source || "list", t.note,
].map(q).join(",")));
writeFileSync(`${base}.csv`, lines.join("\n") + "\n");

// never past a trade this run could not check, and back before one it left
// unchecked (match.mjs nextWatermark / nextSaved)
const st = readState();
const newest = nextSaved(st.last_closed_ms ?? null, report.trades);
if (newest != null && newest !== st.last_closed_ms) {
  writeFileSync(STATE, JSON.stringify({ last_closed_ms: newest, last_closed: fmtWhen(newest),
                                        ran_at: fmtWhen(started) }, null, 2));
}
const missing = Object.entries(report.ids).filter(([, v]) => v.found === false);
console.log(`[audit] verdicts: ${JSON.stringify(counts)}`);
console.log(`[audit] of them, strategies not on the Backtest list (compared from their stored backtests): ${JSON.stringify(counts_not_on_list)}`);
console.log(`[audit] ids with no result: ${missing.length}${missing.length ? ` (${missing.map(([k]) => k).join(", ")})` : ""}`);
for (const line of accuracyLines(report.daily)) console.log(`[audit] ${line}`);
console.log(`[audit] written: ${base}.json and .csv`);
