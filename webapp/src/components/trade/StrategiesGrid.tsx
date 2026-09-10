"use client";
/** Every strategy the runner knows: deployment state, lifetime record, and
 * the arm/disarm + coin/margin editor. Saving POSTs the full settings file
 * and the API records every change to the local deploy history. */
import { useCallback, useEffect, useState } from "react";
import { markReady } from "@/lib/loading";
import { useLiveRefresh } from "@/lib/live";
import PanelStatus from "./PanelStatus";
import CopyableId from "./CopyableId";
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
  // PARTIAL TP/SL (operator, Sep 09, 2026): several strategies share one
  // coin, each holding its own slice of the netted position with its own
  // TP/SL resting at MEXC. Demo defaults ON — that is what demo already
  // does; live defaults OFF, because more slices is more money on one coin.
  const [pDemo, setPDemo] = useState(true);
  const [pLive, setPLive] = useState(false);
  const [pMax, setPMax] = useState(4);
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
        setPDemo((se.settings.partial_tp_demo ?? true) as boolean);
        setPLive((se.settings.partial_tp_live ?? false) as boolean);
        setPMax(Number(se.settings.partial_max_slices ?? 4));
        setAcctCap(st.account_loss_cap); setCapHit(st.account_cap_hit); setFlat(st.flat); setLocks(st.locks);
        markReady("strategies");
      })
      .catch((e) => setErr(String(e))), [catalog]);
  // EVERY 5 SECONDS, and again the moment the tab is looked at. This ran
  // ONCE — the 4-second timer below polls the BACKTEST JOB, not these rows —
  // so LIVE $ and LIVE W/L were frozen at whatever they were when the page
  // opened. The operator's PSXSTOCK stop closed at Sep 10, 2026 8:04pm for
  // −$0.25 and the row went on showing the record from before it until a
  // reload: *"i want the ui realtime when i lose it should show the winrate
  // lose or what ever currently i need to refresh it"*.
  useLiveRefresh(load, 5_000, [load]);

  // the "1 YEAR" grid runs detached, so it survives leaving this page
  useLiveRefresh(() => { api.jobStatus("stratbt").then(setBt).catch(() => {}); },
                 4_000);

  // The "1 YEAR" button that called `tradeApi.backtestStrategy` lived in the
  // `backtest` column, which the operator had removed on 2026-08-27. It was
  // the only trigger in the app for a per-strategy replay; the progress
  // banner below and its polling stay, so a job started elsewhere still
  // reports itself on this screen.

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
    <div className="min-w-0 overflow-hidden rounded-2xl border border-gray-200 bg-white dark:border-white/[0.05] dark:bg-white/[0.03]">
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
          {/* "IF I CLICK IT FORGET THE PREVIOUS LOSS, YOU WILL ASSUME I
              HAVE 0 LOSS AGAIN" (operator, 2026-09-05). A baseline, not a
              deletion: the breaker restarts at zero, the history and the
              today tiles keep the real figure. */}
          <Button size="sm" variant="outline" disabled={busy}
            onClick={async () => {
              if (!window.confirm(
                "Reset the loss-cap counter to 0?" + String.fromCharCode(10) +
                "The loss stays in your history and on the today tiles - " +
                "only the breaker forgets it. Live stays off until you " +
                "tick it back on.")) return;
              try {
                const got = await tradeApi.lossCapReset();
                setNote(`cap counter reset: forgave ${got.forgave.toFixed(2)} USDT, counting from 0 of ${got.limit}`);
                load();
              } catch (e) { setErr(String(e)); }
            }}>RESET CAP</Button>
          <label className="flex flex-col text-theme-xs text-gray-500 dark:text-gray-400">account loss cap $ (0 = off)
            <input type="number" step="1" min={0} value={acctCap}
              onChange={(e) => { const v = Number(e.target.value); setAcctCap(v); mut((s) => { s.loss_limit = v; }); }}
              className="h-9 w-28 rounded-lg border border-gray-200 bg-transparent px-2 text-theme-sm text-gray-700 dark:border-gray-700 dark:text-gray-300" /></label>
          <label className="flex items-center gap-2 text-theme-xs text-gray-600 dark:text-gray-300">
            <input type="checkbox" checked={catalog} onChange={(e) => setCatalog(e.target.checked)} className="h-4 w-4 accent-brand-500" />
            show all {counts.catalog_count} to arm a new one
          </label>
          {/* PARTIAL TP/SL. Each switch says what it does to ITS OWN book and
              nothing about the other — and the live one says the money out
              loud, because turning it on multiplies what one coin can risk. */}
          <label className="flex items-center gap-2 text-theme-xs text-gray-600 dark:text-gray-300"
                 title="Several demo strategies hold the same coin at once, each with its own entry, TP and SL. Off = one demo position per coin, which is what live does with its own switch off.">
            <input type="checkbox" checked={pDemo} className="h-4 w-4 accent-brand-500"
              onChange={(e) => { const v = e.target.checked; setPDemo(v); mut((x) => { x.partial_tp_demo = v; }); }} />
            Enable Partial TP/SL for DEMO
          </label>
          <label className="flex items-center gap-2 text-theme-xs text-gray-600 dark:text-gray-300"
                 title="REAL MONEY: several strategies hold one coin at the same time, each owning a slice of one netted position with its own TP/SL resting at MEXC. Each slice stakes its own margin, so N slices risk N times as much on that coin.">
            <input type="checkbox" checked={pLive} className="h-4 w-4 accent-brand-500"
              onChange={(e) => { const v = e.target.checked; setPLive(v); mut((x) => { x.partial_tp_live = v; }); }} />
            Enable Partial TP/SL for Live
          </label>
          <label className="flex flex-col text-theme-xs text-gray-500 dark:text-gray-400"
                 title="How many strategies may hold one coin at once, per book. Each slice stakes its own margin.">
            max slices per coin
            <input type="number" step="1" min={1} value={pMax}
              onChange={(e) => { const v = Math.max(1, Number(e.target.value) || 1); setPMax(v); mut((x) => { x.partial_max_slices = v; }); }}
              className="h-9 w-24 rounded-lg border border-gray-200 bg-transparent px-2 text-theme-sm text-gray-700 dark:border-gray-700 dark:text-gray-300" />
          </label>
          {(pDemo || pLive) && (
            <span className="text-theme-xs text-gray-500 dark:text-gray-400">
              {/* label-must-match-data: the number is the one the runner will
                  use, and the money is derived from the operator's own stake */}
              up to {pMax} strateg{pMax === 1 ? "y" : "ies"} per coin
              {pLive ? ` · live risks up to ${pMax}x one stake on a coin` : ""}
            </span>
          )}
          {note && !dirty && <span className="text-theme-xs text-success-600">{note}</span>}
          {dirty && <span className="text-theme-xs text-warning-600">unsaved changes</span>}
          {/* "CREATE A BUTTON TO RESET WIN RATE OF ALL" (operator,
              2026-09-05). Archives the trade rows, never deletes them; the
              confirm says the two side effects out loud before anything
              happens. */}
          <Button size="sm" variant="outline" disabled={busy}
            onClick={async () => {
              if (!window.confirm(
                ["Reset the WIN/LOSS record of every strategy, demo AND live?", "",
                 "- the old trades are archived to a backup file, not deleted",
                 "- open demo positions are cleared; real positions are untouched",
                 "- today's loss-cap counter resets too (it reads the same rows)",
                ].join(String.fromCharCode(10)))) return;
              try {
                const got = await tradeApi.recordReset(["paper", "real"]);
                setNote(`record reset: ${got.removed} trades archived to ${got.backup}`);
                load();
              } catch (e) { setErr(String(e)); }
            }}>RESET W/L</Button>
          <Button size="sm" disabled={!dirty || busy} onClick={save}>SAVE CONFIG</Button>
        </div>
      </div>
      <PanelStatus err={err} loaded={settings !== null} />
      {capHit && (
        <p className="mx-5 mt-2 rounded-lg bg-error-50 px-3 py-2 text-theme-sm font-medium text-error-600 dark:bg-error-500/10">
          {/* It used to say "the runner has halted entries" — the cap wrote
              the kill file and the runner EXITED, demo included. Since
              2026-09-04 it switches LIVE off per strategy and leaves the demo
              and the runner alone (operator: "YOU WILL NEED TO SWITCH OFF THE
              LIVE TRADE HERE NO NEED TO STOP RUNNER"). */}
          The account loss cap of ${acctCap} has been reached today — <b>LIVE has been switched off</b> on every strategy. The demo book keeps trading and the runner is still up. Raise the cap and tick LIVE again to resume real money.
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
      {rows.some((r) => (r.streak ?? 0) > 0 && (r.streak_shared_with?.length ?? 0) > 0) && (
        <p className="mx-5 mt-2 rounded-lg bg-warning-50 px-3 py-2 text-theme-xs text-warning-700 dark:bg-warning-500/10">
          {rows.filter((r) => (r.streak ?? 0) > 0 && (r.streak_shared_with?.length ?? 0) > 0)
            .map((r) => `${r.coins.map((c) => c.replace("_USDT", "")).join(",")} ${r.streak_book}: rung ${r.streak} → next stake $${r.next_stake}, shared by ${[r.key, ...(r.streak_shared_with ?? [])].join(" + ")}`)
            .join(" · ")}
          {" "}— the ladder belongs to the coin and book, so a loss by either strategy raises the stake for both.
        </p>
      )}
      {conflicts.length > 0 && (
        <p className="mx-5 mt-2 rounded-lg bg-warning-50 px-3 py-2 text-theme-sm text-warning-700 dark:bg-warning-500/10">
          Timeframe conflict: {conflicts.map((c) => `${c.symbol} on ${(c.keys || []).join(" + ")}`).join(" · ")} — two bots would fight over one MEXC position.
        </p>
      )}
      <div className="w-full">
        <Table fixed>
          <TableHeader>
            <TableRow>
              {/* notional $ and "open now" removed at the operator's request
                  2026-08-21: notional is base x leverage, a number they already
                  know, and "open now" repeats what the positions tables above
                  this one already show. */}
              {/* explicit widths: a table-fixed layout splits columns EVENLY
                  without them, which left "books" too narrow for its two
                  switches and they spilled over the coin beside them. */}
              {/* the widths SUM TO 100. They summed to 109 when the four
                  book columns went in, and a table-fixed layout answers that
                  by squeezing every column: "LIVE W/L" wrapped onto three
                  lines and "DEMO $" broke as "DEM O $". */}
              {([["strategy", "14%"], ["tf", "3%"], ["TP/SL %", "6%"],
                 ["books", "10%"], ["coins", "8%"], ["margin $", "5%"],
                 // `rung` is gone (2026-08-27, operator): the ladder column
                 // already boxes the rung the next stake stands on, and the
                 // live-locked note above the table names it too.
                 [`ladder $ · ${flat ? "flat" : "DEEP"}`, "8%"],
                 ["next $", "4%"], ["loss cap $", "5%"], ["today $", "5%"],
                 // BOTH books, and the money apart from the record. A row
                 // ticked LIVE used to show only its live figures, so there
                 // was nowhere to see what its demo had done; then both were
                 // crammed into one cell each and read as neither
                 // ("its confusing / separate the profit for demo and live",
                 // 2026-08-27). A money column reads down the page.
                 ["LIVE $", "8%"], ["LIVE W/L", "8%"],
                 ["DEMO $", "8%"], ["DEMO W/L", "8%"]] as [string, string][])
                .map(([h, w]) => (
                <TableCell key={h} isHeader style={{ width: w }}
                  className="px-2 py-1.5 text-theme-xs font-medium text-gray-500 text-start dark:text-gray-400">{h}</TableCell>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
            {rows.map((r) => (
              <TableRow key={r.key}>
                <TableCell className="px-2 py-1.5 leading-tight">
                  {/* The stable row ID first, hashed from the combination by the
                      same row_code the reports use — so this is the id to paste
                      into a report's find-by-ID box. The key stays underneath
                      because it is what the runner logs. */}
                  {r.id ? <CopyableId id={r.id} /> : null}
                  {r.label ? (
                    <span className="block text-[10px] font-medium text-brand-500">
                      ({r.label})
                    </span>
                  ) : null}
                  <span className="block text-[10px] text-gray-500 dark:text-gray-400">
                    {r.key.replace(/_/g, "_\u200b")}
                  </span>
                </TableCell>
                <TableCell className="px-2 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{TF[r.interval ?? ""] ?? r.interval}</TableCell>
                <TableCell className="px-2 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">
                  {r.tp != null ? (r.tp * 100).toFixed(2) : "—"} / {r.sl != null ? (r.sl * 100).toFixed(2) : "—"}
                </TableCell>
                <TableCell className="px-2 py-1.5">
                  {/* Side by side, not stacked: two stacked pills made every
                      row twice as tall as it needed to be. */}
                  <div className="flex min-w-0 flex-row flex-wrap items-center gap-1">
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
                          role="switch"
                          aria-checked={r.books.includes(b)}
                          aria-label={b === "real" ? "trade real money" : "simulate only"}
                          className={`inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide transition ${
                            r.books.includes(b)
                              ? b === "real" ? "bg-error-500 text-white" : "bg-success-500 text-white"
                              : locked
                                ? "cursor-not-allowed bg-gray-100 text-gray-300 line-through dark:bg-white/[0.03] dark:text-gray-600"
                                : "bg-gray-100 text-gray-500 dark:bg-white/[0.05] dark:text-gray-400"
                          }`}>
                          {/* the dot IS the switch state, so on/off does not
                              rest on colour alone */}
                          <span className={`h-1.5 w-1.5 rounded-full ${
                            r.books.includes(b) ? "bg-white" : "bg-gray-400 dark:bg-gray-600"}`} />
                          {b === "real" ? "live" : "demo"}
                        </button>
                      );
                    })}
                  </div>
                </TableCell>
                <TableCell className="px-2 py-2 text-theme-xs font-medium text-gray-700 dark:text-gray-300">
                  {/* read-only: the contract is PART of the strategy, not a
                      preference — #3M3CRXP8 IS trend50/30m/2.5/2.0 on PI, and
                      the same signal on another coin is an untested
                      combination (CLAUDE.md rule 21) */}
                  {r.coins.map((c) => c.replace("_USDT", "")).join(", ") || "—"}
                </TableCell>
                <TableCell className="px-2 py-1.5">
                  <input type="number" step="0.5" defaultValue={r.base_margin ?? ""}
                    onBlur={(e) => setMargin(r.key, e.target.value)}
                    className="w-full min-w-0 rounded-lg border border-gray-200 bg-transparent px-1 py-1 text-[11px] text-gray-700 dark:border-gray-700 dark:text-gray-300" />
                </TableCell>
                <TableCell className="px-2 py-1.5">
                  {/* the whole ladder in dollars, with the rung it stands on boxed —
                      so "next $" is never a number to work out */}
                  <div className="flex flex-wrap items-center gap-x-1 gap-y-0.5 text-[10px] leading-tight">
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
                <TableCell className="px-2 py-1.5 text-theme-xs font-semibold text-warning-600">{r.next_stake ?? "—"}</TableCell>
                <TableCell className="px-2 py-1.5">
                  <input type="number" step="0.5" defaultValue={r.loss_cap ?? ""}
                    onBlur={(e) => mut((s) => {
                      const m = ((s.strategy_loss_limits as Record<string, number | null>) ??= {});
                      m[r.key] = e.target.value === "" ? null : Number(e.target.value);
                    })}
                    className="w-full min-w-0 rounded-lg border border-gray-200 bg-transparent px-1 py-1 text-[11px] text-gray-700 dark:border-gray-700 dark:text-gray-300" />
                </TableCell>
                <TableCell className={`px-2 py-1.5 text-theme-xs ${(r.today ?? 0) >= 0 ? "text-success-600" : "text-error-500"}`}>
                  {fmtMoney(r.today)}{r.tripped && <span className="ml-1 font-semibold text-error-500">PAUSED</span>}
                </TableCell>
                {/* TWO cells per book: the money, then the record. A book
                    with nothing on it prints an em dash — "0/0" is a claim
                    about trades that were never attempted, and it was the
                    noise that made this table unreadable. */}
                {([["real", r.real], ["paper", r.paper]] as const).flatMap(([which, b]) => {
                  const armed = b?.armed ?? (which === "real"
                    ? r.books.includes("real") : r.books.includes("paper"));
                  const pnl = b?.pnl ?? 0, w = b?.wins ?? 0, l = b?.losses ?? 0;
                  const n = w + l;
                  const dim = armed ? "" : " opacity-45";
                  const book = which === "real" ? "live" : "demo";
                  return [
                    <TableCell key={`${which}-pnl`}
                      title={armed
                        ? `realized on the ${book} book, all time`
                        : `not armed on the ${book} book`}
                      className={`px-2 py-1.5 text-theme-xs font-semibold${dim} ${
                        n === 0 ? "text-gray-400"
                        : pnl >= 0 ? "text-success-600" : "text-error-500"}`}>
                      {n === 0 ? "—" : fmtMoney(pnl)}
                    </TableCell>,
                    <TableCell key={`${which}-wl`}
                      title={armed
                        ? `${w} won, ${l} lost on the ${book} book`
                        : `not armed on the ${book} book`}
                      className={`px-2 py-1.5 text-theme-xs whitespace-nowrap${dim}`}>
                      {n === 0 ? <span className="text-gray-400">—</span> : (
                        <>
                          <span className="text-success-600">{w}</span>
                          <span className="text-gray-400">/</span>
                          <span className="text-error-500">{l}</span>
                          <span className="ml-1 text-gray-400">
                            {Math.round((100 * w) / n)}%
                          </span>
                        </>
                      )}
                    </TableCell>,
                  ];
                })}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
