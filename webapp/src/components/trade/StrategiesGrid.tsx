"use client";
/** Every strategy the runner knows: deployment state, lifetime record, and
 * the arm/disarm + coin/margin editor. Saving POSTs the full settings file
 * and the API records every change to the local deploy history. */
import { useCallback, useEffect, useState } from "react";
import { api, fmtMoney, JobStatus, tradeApi, StrategyDeployRow } from "@/lib/api";
import Badge from "@/components/ui/badge/Badge";
import Button from "@/components/ui/button/Button";
import { Table, TableBody, TableCell, TableHeader, TableRow } from "@/components/ui/table";

const TF: Record<string, string> = { Min1: "1m", Min15: "15m", Min30: "30m", Min60: "1h", Hour4: "4h", Day1: "1d" };

export default function StrategiesGrid() {
  const [rows, setRows] = useState<StrategyDeployRow[]>([]);
  const [sizing, setSizing] = useState("");
  const [counts, setCounts] = useState({ real_count: 0, paper_count: 0, idle_count: 0, deployed_count: 0, catalog_count: 0 });
  const [acctCap, setAcctCap] = useState(0);
  const [flat, setFlat] = useState(false);
  const [locks, setLocks] = useState<Record<string, { coin: string; held_by: string }>>({});
  const [capHit, setCapHit] = useState(false);
  const [catalog, setCatalog] = useState(false);
  const [conflicts, setConflicts] = useState<{ symbol?: string; keys?: string[] }[]>([]);
  const [settings, setSettings] = useState<Record<string, unknown> | null>(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [note, setNote] = useState("");
  const [bt, setBt] = useState<JobStatus | null>(null);

  const load = useCallback(() =>
    Promise.all([tradeApi.strategies(catalog), tradeApi.settingsGet()])
      .then(([st, se]) => {
        setRows(st.rows); setSizing(st.sizing); setConflicts(st.conflicts);
        setCounts(st); setSettings(se.settings); setDirty(false);
        setAcctCap(st.account_loss_cap); setCapHit(st.account_cap_hit); setFlat(st.flat); setLocks(st.locks);
      })
      .catch((e) => setErr(String(e))), [catalog]);
  useEffect(() => { load(); }, [load]);

  // the "1 YEAR" grid runs detached, so it survives leaving this page
  useEffect(() => {
    const poll = () => api.jobStatus("stratbt").then(setBt).catch(() => {});
    poll();
    const t = setInterval(poll, 4000);
    return () => clearInterval(t);
  }, []);

  const runBacktest = async (key: string) => {
    try {
      await tradeApi.backtestStrategy(key, key);
      setBt({ running: true, key, now: "starting" });
    } catch (e) { setErr(String(e)); }
  };

  const mut = (fn: (s: Record<string, unknown>) => void) => {
    if (!settings) return;
    const next = JSON.parse(JSON.stringify(settings));
    fn(next);
    setSettings(next);
    setDirty(true);
    // reflect immediately in the grid
    setRows((rs) => rs.map((r) => ({
      ...r,
      books: ((next.strategy_books as Record<string, string[]>) || {})[r.key] ?? [],
      coins: ((next.strategy_coins as Record<string, string[]>) || {})[r.key] ?? [],
      base_margin: ((next.strategy_margins as Record<string, number>) || {})[r.key] ?? r.base_margin,
    })));
  };

  const toggleBook = (key: string, book: "real" | "paper") =>
    mut((s) => {
      const books = ((s.strategy_books as Record<string, string[]>) ??= {});
      const cur = new Set(books[key] ?? []);
      if (cur.has(book)) cur.delete(book); else cur.add(book);
      books[key] = [...cur];
    });

  const setCoins = (key: string, text: string) =>
    mut((s) => {
      const coins = ((s.strategy_coins as Record<string, string[]>) ??= {});
      coins[key] = text.split(/[\s,]+/).filter(Boolean).map((c) => (c.toUpperCase().endsWith("_USDT") ? c.toUpperCase() : `${c.toUpperCase()}_USDT`));
    });

  const setMargin = (key: string, v: string) =>
    mut((s) => {
      const m = ((s.strategy_margins as Record<string, number | null>) ??= {});
      m[key] = v === "" ? null : Number(v);
    });

  const save = async () => {
    if (!settings) return;
    const armed = rows.filter((r) => r.books.includes("real")).map((r) => `${r.key} on ${r.coins.map((c) => c.replace("_USDT", "")).join(",")}`);
    if (!confirm(`Save the trading config?\n\nREAL-money strategies after this save:\n${armed.length ? armed.join("\n") : "none"}\n\nThe runner picks this up on its next cycle.`)) return;
    setBusy(true);
    try {
      const got = await tradeApi.settingsSave(settings);
      setNote(`Saved — ${got.changes_recorded} change${got.changes_recorded === 1 ? "" : "s"} recorded to deploy history.`);
      setErr("");
      await load();
    } catch (e) {
      // a 409 is the live-lock guard refusing to net two strategies into one
      // MEXC position — the config on disk is unchanged
      setErr(`NOT saved — ${String(e)}`);
      await load();
    } finally { setBusy(false); }
  };

  return (
    <div className="overflow-hidden rounded-2xl border border-gray-200 bg-white dark:border-white/[0.05] dark:bg-white/[0.03]">
      <div className="flex flex-wrap items-center gap-3 px-5 pt-4">
        <div>
          <h3 className="text-base font-semibold text-gray-800 dark:text-white/90">
            {catalog ? "Strategies · every configurable one" : "Strategies you have deployed"}
          </h3>
          <p className="text-theme-xs text-gray-500 dark:text-gray-400">
            <span className="font-semibold text-error-500">{counts.real_count} trading REAL money</span>
            {" · "}{counts.paper_count} paper only
            {counts.idle_count ? ` · ${counts.idle_count} deployed but switched off` : ""}
            {" · sizing "}{sizing || "—"}
            {catalog ? ` · showing all ${counts.catalog_count} the runner can run` : ""}
          </p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <label className="flex flex-col text-theme-xs text-gray-500 dark:text-gray-400">account loss cap $ (0 = off)
            <input type="number" step="1" min={0} value={acctCap}
              onChange={(e) => { const v = Number(e.target.value); setAcctCap(v); mut((s) => { s.loss_limit = v; }); }}
              className="h-9 w-28 rounded-lg border border-gray-200 bg-transparent px-2 text-theme-sm text-gray-700 dark:border-gray-700 dark:text-gray-300" /></label>
          <label className="flex items-center gap-2 text-theme-xs text-gray-600 dark:text-gray-300">
            <input type="checkbox" checked={catalog} onChange={(e) => setCatalog(e.target.checked)} className="h-4 w-4 accent-brand-500" />
            show all {counts.catalog_count} to arm a new one
          </label>
          {note && !dirty && <span className="text-theme-xs text-success-600">{note}</span>}
          {dirty && <span className="text-theme-xs text-warning-600">unsaved changes</span>}
          <Button size="sm" disabled={!dirty || busy} onClick={save}>SAVE CONFIG</Button>
        </div>
      </div>
      {err && <p className="px-5 pt-2 text-theme-sm text-error-500">{err}</p>}
      {capHit && (
        <p className="mx-5 mt-2 rounded-lg bg-error-50 px-3 py-2 text-theme-sm font-medium text-error-600 dark:bg-error-500/10">
          The account loss cap of ${acctCap} has been reached today — the runner has halted entries. Raise the cap or clear the halt to resume.
        </p>
      )}
      {!!counts.catalog_count && rows.some((r) => r.tripped) && (
        <p className="mx-5 mt-2 rounded-lg bg-warning-50 px-3 py-2 text-theme-sm text-warning-700 dark:bg-warning-500/10">
          Paused for the rest of today (their own loss cap was hit): {rows.filter((r) => r.tripped).map((r) => r.key).join(", ")}. The others keep trading.
        </p>
      )}
      {bt && (bt.running || bt.report || bt.error) && (
        <p className="mx-5 mt-2 rounded-lg bg-gray-50 px-3 py-2 text-theme-sm dark:bg-white/[0.03]">
          {bt.running
            ? <span className="text-gray-600 dark:text-gray-300">
                Backtesting <b>{bt.key}</b> over 365 days — {bt.done ?? 0}% · {bt.now ?? ""} · runs detached, you can leave this page
              </span>
            : bt.error
              ? <span className="text-error-500">{bt.key} backtest failed: {bt.error}</span>
              : <a href={bt.report_url ?? `/api/reports/file/${bt.report}`} target="_blank" rel="noopener"
                   className="font-medium text-brand-500 hover:underline">
                  OPEN THE {bt.key} GRID ↗ {bt.cached ? "(cached)" : `· ${bt.rows ?? ""} rows`}
                </a>}
        </p>
      )}
      {Object.keys(locks).length > 0 && (
        <p className="mx-5 mt-2 rounded-lg bg-gray-50 px-3 py-2 text-theme-xs text-gray-600 dark:bg-white/[0.03] dark:text-gray-300">
          live-locked: {Object.entries(locks).map(([k, v]) =>
            `${k} (${v.coin.replace("_USDT", "")} held by ${v.held_by})`).join(" · ")} — one coin runs one timeframe with real money.
        </p>
      )}
      {conflicts.length > 0 && (
        <p className="mx-5 mt-2 rounded-lg bg-warning-50 px-3 py-2 text-theme-sm text-warning-700 dark:bg-warning-500/10">
          Timeframe conflict: {conflicts.map((c) => `${c.symbol} on ${(c.keys || []).join(" + ")}`).join(" · ")} — two bots would fight over one MEXC position.
        </p>
      )}
      <div className="max-w-full overflow-x-auto p-2">
        <Table>
          <TableHeader>
            <TableRow>
              {["strategy", "tf", "TP/SL %", "books", "coins", "margin $", "notional $", "streak", `ladder $ · ${flat ? "flat" : "DEEP"}`, "next $",
                "loss cap $", "today $", "PROFIT $", "trades", "W", "L", "open now", "backtest"].map((h) => (
                <TableCell key={h} isHeader className="px-3 py-2 text-theme-xs font-medium text-gray-500 text-start dark:text-gray-400">{h}</TableCell>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
            {rows.map((r) => (
              <TableRow key={r.key}>
                <TableCell className="px-3 py-2 text-theme-sm font-medium text-gray-800 dark:text-white/90">{r.key}</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{TF[r.interval ?? ""] ?? r.interval}</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">
                  {r.tp != null ? (r.tp * 100).toFixed(2) : "—"} / {r.sl != null ? (r.sl * 100).toFixed(2) : "—"}
                </TableCell>
                <TableCell className="px-3 py-2">
                  <div className="flex gap-1">
                    {(["real", "paper"] as const).map((b) => {
                      // a coin already traded LIVE on another timeframe cannot
                      // take a second live strategy: MEXC nets them into one
                      // position. DEMO is never locked.
                      const locked = b === "real" && !!r.live_locked && !r.books.includes("real");
                      return (
                        <button key={b} onClick={() => !locked && toggleBook(r.key, b)}
                          disabled={locked}
                          title={locked
                            ? `${r.live_locked!.coin.replace("_USDT", "")} is already traded live by ${r.live_locked!.held_by} on another timeframe — MEXC nets them into one position`
                            : undefined}
                          className={`rounded-full px-2.5 py-0.5 text-theme-xs font-medium transition ${
                            r.books.includes(b)
                              ? b === "real" ? "bg-error-500 text-white" : "bg-success-500 text-white"
                              : locked
                                ? "cursor-not-allowed bg-gray-100 text-gray-300 line-through dark:bg-white/[0.03] dark:text-gray-600"
                                : "bg-gray-100 text-gray-500 dark:bg-white/[0.05] dark:text-gray-400"
                          }`}>
                          {b === "real" ? "REAL" : "paper"}
                        </button>
                      );
                    })}
                  </div>
                </TableCell>
                <TableCell className="px-3 py-2">
                  <input defaultValue={r.coins.map((c) => c.replace("_USDT", "")).join(", ")}
                    onBlur={(e) => setCoins(r.key, e.target.value)}
                    className="w-36 rounded-lg border border-gray-200 bg-transparent px-2 py-1 text-theme-xs text-gray-700 dark:border-gray-700 dark:text-gray-300" />
                </TableCell>
                <TableCell className="px-3 py-2">
                  <input type="number" step="0.5" defaultValue={r.base_margin ?? ""}
                    onBlur={(e) => setMargin(r.key, e.target.value)}
                    className="w-16 rounded-lg border border-gray-200 bg-transparent px-2 py-1 text-theme-xs text-gray-700 dark:border-gray-700 dark:text-gray-300" />
                </TableCell>
                <TableCell className="px-3 py-2 text-theme-xs text-gray-500 dark:text-gray-400">{r.notional ?? "—"}</TableCell>
                <TableCell className="px-3 py-2 text-theme-xs">
                  {r.streak ? <span className="font-medium text-error-500">{r.streak} loss</span>
                            : <span className="text-gray-400">—</span>}
                </TableCell>
                <TableCell className="px-3 py-2">
                  {/* the whole ladder in dollars, with the rung it stands on boxed —
                      so "next $" is never a number to work out */}
                  <div className="flex flex-wrap items-center gap-0.5 text-theme-xs">
                    {(r.ladder ?? []).map((amt, i) => (
                      <span key={i} className={i === (r.ladder_rung ?? 0) && !flat
                        ? "rounded bg-warning-400 px-1 font-bold text-gray-900"
                        : "px-0.5 text-gray-400"}>
                        {amt}
                      </span>
                    ))}
                    {flat && <span className="ml-1 text-gray-400">every trade</span>}
                  </div>
                </TableCell>
                <TableCell className="px-3 py-2 text-theme-sm font-semibold text-warning-600">{r.next_stake ?? "—"}</TableCell>
                <TableCell className="px-3 py-2">
                  <input type="number" step="0.5" defaultValue={r.loss_cap ?? ""}
                    onBlur={(e) => mut((s) => {
                      const m = ((s.strategy_loss_limits as Record<string, number | null>) ??= {});
                      m[r.key] = e.target.value === "" ? null : Number(e.target.value);
                    })}
                    className="w-16 rounded-lg border border-gray-200 bg-transparent px-2 py-1 text-theme-xs text-gray-700 dark:border-gray-700 dark:text-gray-300" />
                </TableCell>
                <TableCell className={`px-3 py-2 text-theme-xs ${(r.today ?? 0) >= 0 ? "text-success-600" : "text-error-500"}`}>
                  {fmtMoney(r.today)}{r.tripped && <span className="ml-1 font-semibold text-error-500">PAUSED</span>}
                </TableCell>
                <TableCell className={`px-3 py-2 text-theme-sm font-semibold ${r.pnl >= 0 ? "text-success-600" : "text-error-500"}`}>{fmtMoney(r.pnl)}</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{r.trades}</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm text-success-600">{r.wins}</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm text-error-500">{r.losses}</TableCell>
                <TableCell className="px-3 py-2 text-theme-xs text-gray-500 dark:text-gray-400">
                  <div className="flex flex-wrap items-center gap-1">
                    {r.open_on.map((c) => (
                      <span key={`r${c}`} className="rounded bg-error-50 px-1.5 py-0.5 font-medium text-error-600 dark:bg-error-500/15">
                        {c.replace("_USDT", "")} real
                      </span>
                    ))}
                    {r.open_on_paper.map((c) => (
                      <span key={`p${c}`} className="rounded bg-gray-100 px-1.5 py-0.5 text-gray-500 dark:bg-white/[0.06] dark:text-gray-400">
                        {c.replace("_USDT", "")} paper
                      </span>
                    ))}
                    {!r.open_on.length && !r.open_on_paper.length && <span>—</span>}
                    {r.books.includes("real") && <Badge size="sm" color="error">ARMED</Badge>}
                  </div>
                </TableCell>
                <TableCell className="px-3 py-2">
                  <button onClick={() => runBacktest(r.key)}
                    disabled={!r.coins.length || (bt?.running && bt.key === r.key)}
                    title={`Replay ${r.key} over the last 365 days of MEXC history at this row's base margin.`}
                    className="rounded-lg border border-gray-200 px-2 py-1 text-theme-xs font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-40 dark:border-gray-700 dark:text-gray-300">
                    {bt?.running && bt.key === r.key ? `${bt.done ?? 0}%` : "1 YEAR"}
                  </button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
