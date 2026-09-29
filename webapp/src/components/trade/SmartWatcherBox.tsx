"use client";
/** "Smart Watcher" — ONE box that switches the strategy watcher on and off.
 *
 *  Operator, Sep 29, 2026: *"can you create a checkbox called 'Smart
 *  Watcher' if this is on, it should auto promote and demote, if its off,
 *  dont demote or promote anything, but still the scheduled github backest
 *  run should still run every 24 hrs wether this is on or off"*.
 *
 *  Ticked is the watcher's "act" mode, unticked is "off". It applies AT ONCE
 *  (POST /api/trade/watcher) — it is not part of SAVE CONFIG, because the
 *  watcher's mode is not a setting the runner reads. The daily UPDATE ALL
 *  BACKTESTS is a different switch (Backtest v2) and runs either way.
 *
 *  Drawn in two places (the deployed-strategies toolbar and the Watcher
 *  panel); a change in one is sent to the other with the "smart-watcher"
 *  window event, so they never disagree.
 */
import { useCallback, useEffect, useState } from "react";
import { api, Watcher } from "@/lib/api";
import { useLiveRefresh } from "@/lib/live";

export const WATCHER_EVENT = "smart-watcher";

export default function SmartWatcherBox({ onChange }: { onChange?: (w: Watcher) => void }) {
  const [w, setW] = useState<Watcher | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const load = useCallback(() => api.watcher().then((d) => { setW(d); setErr(""); })
    .catch((e) => setErr(String(e))), []);
  useLiveRefresh(load, 30_000);
  useEffect(() => {
    const on = (e: Event) => setW((e as CustomEvent<Watcher>).detail);
    window.addEventListener(WATCHER_EVENT, on);
    return () => window.removeEventListener(WATCHER_EVENT, on);
  }, []);

  const set = (v: boolean) => {
    if (v && !window.confirm(
      ["Turn Smart Watcher ON?", "",
       "Every hour it switches OFF any practice row whose last 30 days fall under the line — your own rows too.",
       "Once a day at noon it switches ON new practice rows that pass your rules.", "",
       "It never touches real money."].join(String.fromCharCode(10)))) return;
    setBusy(true);
    api.watcherSet({ mode: v ? "act" : "off" })
      .then((d) => {
        setW(d); setErr("");
        window.dispatchEvent(new CustomEvent(WATCHER_EVENT, { detail: d }));
        onChange?.(d);
      })
      .catch((e) => setErr(String(e)))
      .finally(() => setBusy(false));
  };

  const on = w?.mode === "act";
  return (
    <label className={`flex items-center gap-2 text-theme-xs ${on
      ? "font-semibold text-brand-600 dark:text-brand-400" : "text-gray-600 dark:text-gray-300"}`}
      title={w ? (on
        ? `ON: switches practice rows on at ${w.cfg.on_winrate}%+ and off under ${w.cfg.off_winrate}% over the last ${w.window_days} days — your own practice rows too. The daily backtest update runs either way.`
        : "OFF: switches nothing on and nothing off. The daily backtest update still runs every 24 hours.")
        : "reading the watcher…"}>
      <input type="checkbox" checked={on} disabled={!w || busy}
        className="h-4 w-4 accent-brand-500"
        onChange={(e) => set(e.target.checked)} />
      Smart Watcher
      {w?.mode === "preview" && <span className="font-normal text-gray-400">(preview — changes nothing)</span>}
      {err && <span className="font-normal text-error-500">{err}</span>}
    </label>
  );
}
