"use client";
/** The strategy watcher — what it switched on and off in the practice
 *  account, and why (tradingagents/strategy_watcher.py).
 *
 *  Operator, Sep 29, 2026: "deploy now the wathcer replay, /goal i want this
 *  fully working, the backtest everyday the promotion and demotion". Every
 *  word here comes from GET /api/trade/watcher: the mode, the rules, the
 *  counts and each decision's own sentence, which already names the row id.
 */
import { useCallback, useEffect, useState } from "react";
import { fmtWhen, Watcher, WatcherDecision } from "@/lib/api";
import { useVenueName } from "@/lib/venue";
import { useRoom, useRoomApis } from "@/lib/room";
import { useLiveRefresh } from "@/lib/live";
import { pageWindow } from "@/lib/pager";
import SmartWatcherBox, { WATCHER_EVENT } from "./SmartWatcherBox";

/** TEN A PAGE (operator, Sep 29, 2026: "paginate the Watcher"), the same
 *  size and the same buttons as the positions table. */
const PER_PAGE = 10;
const pageNum = "h-8 min-w-8 rounded-lg border px-2 text-theme-xs tabular-nums";
const pageBtn = "h-8 rounded-lg border border-gray-300 px-2 text-theme-xs text-gray-600 "
  + "disabled:opacity-40 dark:border-gray-700 dark:text-gray-300";

function Pager({ cur, pages, goto, what }: {
  cur: number; pages: number; goto: (n: number) => void; what: string;
}) {
  if (pages <= 1) return null;
  return (
    <div className="mt-2 flex flex-wrap items-center gap-1">
      <button onClick={() => goto(cur - 1)} disabled={cur === 1} className={pageBtn}>prev</button>
      {pageWindow(cur, pages).map((n, i) => n == null ? (
        <span key={`gap${i}`} aria-hidden className="px-1 text-theme-xs text-gray-400">…</span>
      ) : (
        <button key={n} onClick={() => goto(n)} aria-label={`${what} page ${n}`}
          aria-current={n === cur ? "page" : undefined}
          className={`${pageNum} ${n === cur
            ? "border-brand-500 bg-brand-500 font-semibold text-white"
            : "border-gray-300 text-gray-600 hover:border-brand-400 dark:border-gray-700 dark:text-gray-300"}`}>
          {n}
        </button>
      ))}
      <button onClick={() => goto(cur + 1)} disabled={cur === pages} className={pageBtn}>next</button>
      <span className="text-theme-xs text-gray-500 dark:text-gray-400">of {pages}</span>
    </div>
  );
}

const ACTION: Record<WatcherDecision["action"], { label: string; cls: string }> = {
  on: { label: "switched on", cls: "text-success-600" },
  off: { label: "switched off", cls: "text-error-500" },
  refused: { label: "refused", cls: "text-warning-600 dark:text-warning-400" },
  report: { label: "note", cls: "text-gray-500 dark:text-gray-400" },
};

const MODE_TEXT: Record<Watcher["mode"], string> = {
  act: "Smart Watcher is ON — switching practice rows on and off by itself, your own practice rows included",
  preview: "PREVIEW — it decides and changes nothing",
  off: "Smart Watcher is OFF — it switches nothing on or off; the daily backtest update still runs",
};

/** The rules as the operator reads them — shared by this panel and the
 *  tab "i" popup, so the two can never say different things. The last line
 *  follows the room's real-money switch (label-must-match-data). */
export function rules(c: Watcher["cfg"], days: number, live = false): string[] {
  // THE SWITCH-OFF'S OWN WINDOW (Oct 07, 2026: the 1-4 day rooms switch on by
  // their last few days and off on "the DEMO 30 DAYS figure"); 0 = the same
  const judge = Number(c.judge_days) || days;
  const d = (n: number) => `${n} day${n === 1 ? "" : "s"}`;
  return [
    `switch on at ${c.on_winrate}%+ over the last ${d(days)}`,
    `switch off under ${c.off_winrate}%`,
    judge === days ? `${c.min_trades}+ trades`
      : `${c.min_trades}+ trades ${days === 1 ? "in that day" : `in those ${days} days`}`,
    c.tp_rule === "any" ? "any TP" : `TP ${c.tp_rule === ">" ? "wider than" : c.tp_rule === "<" ? "narrower than"
      : c.tp_rule === "=" ? "equal to" : "at least"} SL`,
    ...(c.max_sl ? [`SL no wider than ${c.max_sl}%`] : []),
    ...(c.min_tp ? [`TP at least ${c.min_tp}%`] : []),
    // RAW (Sep 30, 2026: "i want raw output, dont put any limit"): the
    // criteria above and nothing else
    ...(c.raw ? ["every matching row in the Backtest v2 table, no limit"] : [
      [c.max_slots ? `up to ${c.max_slots} at once` : "no limit at once",
       c.max_per_coin ? `${c.max_per_coin} per coin` : "no limit per coin",
       c.max_new_per_day ? `${c.max_new_per_day} new a day` : "no limit a day"].join(" · "),
      `${c.cooldown_days}-day wait after a switch-off`]),
    judge !== days
      ? `switched on by its last ${d(days)}, switched off on the DEMO ${judge} DAYS figure — and never switched on while that is under ${c.off_winrate}%`
      : days === 30 ? "judged on the DEMO 30 DAYS figure"
      : `judged on its own last ${days} days: the backtest, then its practice trades`,
    live ? "practice AND real money" : "practice account only",
  ];
}

export default function WatcherPanel() {
  const venueName = useVenueName();
  // this panel's own room, even while its tab is not the one on screen
  const { api } = useRoomApis();
  const room = useRoom();
  const [w, setW] = useState<Watcher | null>(null);
  const [err, setErr] = useState("");
  // the decisions page is asked of the SERVER; the running rows arrive whole
  // and page here
  const [dPage, setDPage] = useState(1);
  const [sPage, setSPage] = useState(1);
  const load = useCallback(() => api.watcher(dPage).then((d) => { setW(d); setErr(""); })
    .catch((e) => setErr(String(e))), [api, dPage]);
  useLiveRefresh(load, 30_000, [load]);
  // the Smart Watcher box changes the same mode; its answer carries page 1
  // of the decisions, so only the mode and the status line are taken from it
  useEffect(() => {
    const on = (e: Event) => {
      const d = (e as CustomEvent<Watcher>).detail;
      // every room is on the page now: take only THIS room's switch
      if (room && (d as { profile?: string }).profile && (d as { profile?: string }).profile !== room.id) return;
      setW((p) => (p ? { ...p, mode: d.mode, why: d.why } : d));
    };
    window.addEventListener(WATCHER_EVENT, on);
    return () => window.removeEventListener(WATCHER_EVENT, on);
  }, [room]);
  const sPages = w ? Math.max(1, Math.ceil(w.slots.length / PER_PAGE)) : 1;
  const sCur = Math.min(sPage, sPages);
  const slotsShown = w ? w.slots.slice((sCur - 1) * PER_PAGE, sCur * PER_PAGE) : [];

  return (
    <div className="min-w-0 overflow-hidden rounded-2xl border border-gray-200 bg-white p-5 dark:border-white/[0.05] dark:bg-white/[0.03]">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-gray-800 dark:text-white/90">Watcher</h3>
          <p className="text-theme-xs text-gray-500 dark:text-gray-400">
            {w ? MODE_TEXT[w.mode] : "reading…"}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-4">
          <SmartWatcherBox onChange={(d) => setW((p) => (p ? { ...p, mode: d.mode, why: d.why } : d))} />
          {/* THIS ROOM ALSO TRADES REAL MONEY (Sep 29, 2026: "i want both,
              if i enable live trade, then it should be included"). Off by
              default; turning it off takes real money off every row this
              watcher armed with it and keeps their practice half. */}
          {w && (
            <label className={`flex items-center gap-2 text-theme-xs ${w.live
              ? "font-semibold text-error-600 dark:text-error-400" : "text-gray-600 dark:text-gray-300"}`}
              title="When on, the rows this watcher switches on also trade REAL money, and it switches their real money off by the same rule. Every real-money check still applies to every trade.">
              <input type="checkbox" checked={!!w.live} className="h-4 w-4 accent-error-500"
                onChange={(e) => {
                  const v = e.target.checked;
                  if (v && !window.confirm(
                    ["Let this room's watcher trade REAL money?", "",
                     `Rows it switches on will open real trades on your ${venueName} account.`,
                     "Only one room can hold a coin with real money at a time."]
                      .join(String.fromCharCode(10)))) return;
                  api.watcherSet({ live: v }).then(setW).catch((er) => setErr(String(er)));
                }} />
              Watcher trades real money
            </label>
          )}
        </div>
      </div>
      {err && <p className="mt-2 text-theme-xs text-error-500">{err}</p>}
      {w && (
        <>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {rules(w.cfg, w.window_days, !!w.live).map((t) => (
              <span key={t} className="rounded-full border border-gray-200 px-2.5 py-0.5 text-theme-xs text-gray-600 dark:border-white/[0.08] dark:text-gray-300">{t}</span>
            ))}
          </div>
          <p className="mt-3 text-theme-xs text-gray-500 dark:text-gray-400">
            <b className="text-gray-700 dark:text-gray-300">{w.running}</b> row{w.running === 1 ? "" : "s"} running
            {" · "}{w.cooling} waiting out a switch-off
            {" · "}last switch-on check {w.last_on_pass ? fmtWhen(w.last_on_pass) : "not yet"}
            {w.next_on_pass ? ` · next ${fmtWhen(w.next_on_pass)}` : ""}
            {" · "}last switch-off check {w.last_off_pass ? fmtWhen(w.last_off_pass) : "not yet"}
          </p>
          {w.why && <p className="mt-1 text-theme-xs text-gray-500 dark:text-gray-400">{w.why}</p>}
          {w.slots.length > 0 && (
            <div className="mt-3 flex flex-col gap-1">
              <p className="text-theme-xs font-semibold text-gray-700 dark:text-gray-300">
                Running now · {w.slots.length}
              </p>
              {slotsShown.map((s) => (
                <div key={s.slot} className="flex flex-wrap gap-x-2 text-theme-xs text-gray-600 dark:text-gray-300">
                  <span className="font-mono text-brand-500">#{s.id}</span>
                  <span>{s.coin} {s.tf} {s.signal} · TP {s.tp}% / SL {s.sl}%</span>
                  <span className="text-gray-400">on since {fmtWhen(s.on_at)}</span>
                  {s.practice && (
                    <span>practice: {s.practice.trades} trades, {s.practice.wins} won, {s.practice.losses} lost, {s.practice.pnl >= 0 ? "+" : ""}{s.practice.pnl.toFixed(2)}</span>
                  )}
                  {s.practice?.warn && <span className="text-warning-600 dark:text-warning-400">{s.practice.warn}</span>}
                </div>
              ))}
              <Pager cur={sCur} pages={sPages} goto={(n) => setSPage(Math.min(Math.max(1, n), sPages))}
                what="running" />
            </div>
          )}
          <p className="mt-3 text-theme-xs font-semibold text-gray-700 dark:text-gray-300">
            Decisions · {w.decisions_total}
            {/* the page waits its turn behind the screen's other requests
                (~4 s measured), so the click is answered at once */}
            {w.decisions_page !== dPage && (
              <span className="ml-2 font-normal text-gray-400">loading page {dPage}…</span>
            )}
          </p>
          <div className="mt-1 flex flex-col gap-1.5">
            {w.decisions.length === 0 && (
              <p className="text-theme-xs text-gray-400">
                {w.mode === "off" ? "switched off — it makes no decisions"
                  : "no decision yet — the first check runs a minute after the site starts"}
              </p>
            )}
            {w.decisions.map((d, i) => (
              <div key={`${d.at}-${d.id}-${i}`}
                className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 border-b border-gray-100 py-1 text-theme-xs dark:border-white/[0.05]">
                <span className="text-gray-400">{fmtWhen(d.at)}</span>
                <span className={`font-semibold ${ACTION[d.action].cls}`}>{ACTION[d.action].label}</span>
                {d.mode !== "act" && <span className="text-gray-400">({d.mode})</span>}
                <span className="min-w-0 break-words text-gray-700 dark:text-gray-300">{d.why}</span>
              </div>
            ))}
          </div>
          <Pager cur={Math.min(dPage, w.decisions_pages)} pages={w.decisions_pages}
            goto={(n) => setDPage(Math.min(Math.max(1, n), w.decisions_pages))} what="decisions" />
        </>
      )}
    </div>
  );
}
