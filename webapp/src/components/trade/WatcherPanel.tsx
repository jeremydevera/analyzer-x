"use client";
/** The strategy watcher — what it switched on and off in the practice
 *  account, and why (tradingagents/strategy_watcher.py).
 *
 *  Operator, Sep 29, 2026: "deploy now the wathcer replay, /goal i want this
 *  fully working, the backtest everyday the promotion and demotion". Every
 *  word here comes from GET /api/trade/watcher: the mode, the rules, the
 *  counts and each decision's own sentence, which already names the row id.
 */
import { useCallback, useState } from "react";
import { api, fmtWhen, Watcher, WatcherDecision } from "@/lib/api";
import { useLiveRefresh } from "@/lib/live";

const ACTION: Record<WatcherDecision["action"], { label: string; cls: string }> = {
  on: { label: "switched on", cls: "text-success-600" },
  off: { label: "switched off", cls: "text-error-500" },
  refused: { label: "refused", cls: "text-warning-600 dark:text-warning-400" },
  report: { label: "your row", cls: "text-gray-500 dark:text-gray-400" },
};

const MODE_TEXT: Record<Watcher["mode"], string> = {
  act: "switching practice rows on and off by itself",
  preview: "PREVIEW — it decides and changes nothing",
  off: "switched off — it changes nothing",
};

function rules(c: Watcher["cfg"], days: number): string[] {
  return [
    `switch on at ${c.on_winrate}%+ over the last ${days} days`,
    `switch off under ${c.off_winrate}%`,
    `${c.min_trades}+ trades`,
    `TP ${c.tp_rule === ">" ? "wider than" : "at least"} SL`,
    `up to ${c.max_slots} at once · ${c.max_per_coin} per coin · ${c.max_new_per_day} new a day`,
    `${c.cooldown_days}-day wait after a switch-off`,
    "practice account only",
  ];
}

export default function WatcherPanel() {
  const [w, setW] = useState<Watcher | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => api.watcher().then((d) => { setW(d); setErr(""); })
    .catch((e) => setErr(String(e))), []);
  useLiveRefresh(load, 30_000);

  const setMode = (mode: Watcher["mode"]) => {
    if (mode === "act" && !confirm("Let the watcher switch PRACTICE rows on and off by itself?\n\n"
      + "It never touches real money or the rows you armed yourself.")) return;
    setBusy(true);
    api.watcherSet({ mode }).then(setW).catch((e) => setErr(String(e))).finally(() => setBusy(false));
  };

  return (
    <div className="min-w-0 overflow-hidden rounded-2xl border border-gray-200 bg-white p-5 dark:border-white/[0.05] dark:bg-white/[0.03]">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-gray-800 dark:text-white/90">Watcher</h3>
          <p className="text-theme-xs text-gray-500 dark:text-gray-400">
            {w ? MODE_TEXT[w.mode] : "reading…"}
          </p>
        </div>
        {w && (
          <div className="flex gap-1" role="group" aria-label="Watcher mode">
            {(["act", "preview", "off"] as const).map((m) => (
              <button key={m} type="button" disabled={busy} onClick={() => setMode(m)}
                aria-pressed={w.mode === m}
                className={`rounded-lg border px-3 py-1 text-theme-xs font-medium ${w.mode === m
                  ? "border-brand-500 bg-brand-500 text-white"
                  : "border-gray-300 text-gray-600 hover:border-brand-400 dark:border-gray-700 dark:text-gray-300"}`}>
                {m === "act" ? "on" : m}
              </button>
            ))}
          </div>
        )}
      </div>
      {err && <p className="mt-2 text-theme-xs text-error-500">{err}</p>}
      {w && (
        <>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {rules(w.cfg, w.window_days).map((t) => (
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
              <p className="text-theme-xs font-semibold text-gray-700 dark:text-gray-300">Running now</p>
              {w.slots.map((s) => (
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
            </div>
          )}
          <div className="mt-3 flex flex-col gap-1.5">
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
        </>
      )}
    </div>
  );
}
