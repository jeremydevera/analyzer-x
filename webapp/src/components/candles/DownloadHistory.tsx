"use client";
/** Every download this machine has run, newest first, with its OUTCOME.
 *
 * The job's progress file only holds the LAST run, so the history comes from
 * the local event store. The operator asked to see "if it was success" —
 * before this, a finished download left nothing behind that said so.
 *
 * Two tabs and grouped errors, asked for on 2026-09-02: *"there are so many
 * text here / can you group the error messages in download history section /
 * and create 'error' tab and success tab"*. One run had named 26 lost pairs as
 * 26 separate sentences, five of them the same contract saying the same thing
 * about five timeframes.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { DownloadHistory as Payload, DownloadHistoryRow, notifyApi } from "@/lib/api";

/** "AJINOMOTOSTOCK_USDT 15m: no Min15 candles for AJINOMOTOSTOCK_USDT"
 *  -> { coin: "AJINOMOTOSTOCK", tf: "15m", why: "no candles for this contract" }
 *
 *  The reason is normalised so the same fault on five timeframes collapses to
 *  one line. `no Min15 candles` and `no Hour4 candles` are the same sentence
 *  with the timeframe spliced in, and reading it five times tells you nothing
 *  the timeframe list does not.
 */
function parseFailure(text: string) {
  const m = /^([A-Z0-9]+)_USDT\s+(\d+[mhd]|1d)\s*:\s*(.*)$/i.exec(text.trim());
  if (!m) return { coin: "", tf: "", why: text.trim() };
  const why = m[3]
    .replace(/no (Min\d+|Hour\d+|Day\d+) candles for \S+/i, "no candles served")
    .replace(/\s+/g, " ")
    .trim();
  return { coin: m[1], tf: m[2], why };
}

/** One line per (contract, reason), listing the timeframes it hit. */
function groupFailures(texts: string[]) {
  const by = new Map<string, { coin: string; why: string; tfs: string[] }>();
  for (const t of texts) {
    const { coin, tf, why } = parseFailure(t);
    const key = `${coin}|${why}`;
    const got = by.get(key) ?? { coin, why, tfs: [] };
    if (tf && !got.tfs.includes(tf)) got.tfs.push(tf);
    by.set(key, got);
  }
  const order = ["15m", "30m", "1h", "4h", "1d"];
  return [...by.values()].map((g) => ({
    ...g,
    tfs: g.tfs.sort((a, b) => order.indexOf(a) - order.indexOf(b)),
  }));
}

const TABS = [
  { id: "fail", label: "errors" },
  { id: "ok", label: "success" },
] as const;
type Tab = (typeof TABS)[number]["id"];

function Run({ r }: { r: DownloadHistoryRow }) {
  const [open, setOpen] = useState(false);
  const named = useMemo(
    () => groupFailures((r.lost ?? []).map((p) => `${p.symbol} ${p.timeframe}: ${p.recovered ? "recovered" : "still lost"}`)),
    [r.lost],
  );
  const stillLost = (r.lost ?? []).filter((p) => !p.recovered).length;
  const recovered = (r.lost ?? []).filter((p) => p.recovered).length;

  return (
    <li className="border-b border-gray-50 pb-2 last:border-0 dark:border-gray-800/60">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase ${
          r.stopped
            ? "bg-gray-100 text-gray-500 dark:bg-white/[0.06] dark:text-gray-400"
            : r.ok
              ? "bg-success-50 text-success-700 dark:bg-success-500/15 dark:text-success-400"
              : r.resolved
                ? "bg-gray-100 text-gray-600 dark:bg-white/[0.06] dark:text-gray-300"
                : "bg-error-50 text-error-700 dark:bg-error-500/15 dark:text-error-400"}`}>
          {r.stopped ? "stopped" : r.ok ? "success" : r.resolved ? "failed · resolved" : "failed"}
        </span>
        <span className="font-mono text-theme-xs text-gray-700 dark:text-gray-300">
          {(r.bars ?? 0).toLocaleString()} bars
        </span>
        <span className="text-theme-xs text-gray-500 dark:text-gray-400">
          {(r.pairs ?? 0).toLocaleString()} pair{r.pairs === 1 ? "" : "s"} · {r.mode}
          {r.errors ? ` · ${r.errors} error${r.errors === 1 ? "" : "s"}` : ""}
        </span>
        <span className="ml-auto text-theme-xs text-gray-400 dark:text-gray-500">
          {r.when}
        </span>
      </div>

      {/* the grouped summary — one line per contract, not one per timeframe */}
      {!r.ok && named.length > 0 && (
        <div className="mt-1 flex flex-wrap items-baseline gap-x-2 gap-y-1">
          {named.slice(0, open ? named.length : 6).map((g) => (
            <span key={`${g.coin}-${g.why}`}
              className={`rounded px-1.5 py-0.5 text-[11px] ${
                g.why === "recovered"
                  ? "bg-success-50 text-success-700 dark:bg-success-500/15 dark:text-success-400"
                  : "bg-error-50 text-error-700 dark:bg-error-500/15 dark:text-error-400"}`}>
              <b className="font-semibold">{g.coin.replace("_USDT", "")}</b>
              {g.tfs.length ? ` ${g.tfs.join(" ")}` : ""}
              {g.tfs.length === 5 ? " (all)" : ""}
              {g.why === "recovered" ? " · recovered" : ""}
            </span>
          ))}
          {named.length > 6 && (
            <button onClick={() => setOpen(!open)}
              className="text-[11px] font-medium text-brand-500 hover:underline">
              {open ? "show fewer" : `+${named.length - 6} more contract${named.length - 6 === 1 ? "" : "s"}`}
            </button>
          )}
        </div>
      )}

      {/* the counts, once, instead of a sentence per pair */}
      {!r.ok && (stillLost || recovered || r.unnamed) ? (
        <p className="mt-1 text-theme-xs">
          {stillLost ? (
            <span className="text-error-500">{stillLost} pair{stillLost === 1 ? "" : "s"} still lost</span>
          ) : null}
          {stillLost && recovered ? <span className="text-gray-400"> · </span> : null}
          {recovered ? (
            <span className="text-success-600 dark:text-success-400">
              {recovered} recovered since
            </span>
          ) : null}
          {r.unnamed ? (
            <span className="text-gray-500 dark:text-gray-400">
              {stillLost || recovered ? " · " : ""}
              {r.unnamed} more not named by that run
            </span>
          ) : null}
          <button onClick={() => setOpen(!open)}
            className="ml-2 text-[11px] font-medium text-brand-500 hover:underline">
            {open ? "hide the detail" : "what happened"}
          </button>
        </p>
      ) : null}

      {/* the run's own sentence, and the per-pair detail, only when asked for */}
      {open && (
        <div className="mt-1 rounded-lg bg-gray-50 p-2 dark:bg-white/[0.03]">
          {r.detail && (
            <p className={`break-words text-theme-xs ${
              r.resolved ? "text-gray-400 line-through dark:text-gray-500" : "text-gray-600 dark:text-gray-300"}`}>
              {r.detail}
            </p>
          )}
          {r.resolved_why && (
            <p className={`mt-1 break-words text-theme-xs font-medium ${
              r.resolved ? "text-success-600 dark:text-success-400" : "text-error-500"}`}>
              {r.resolved_why}
            </p>
          )}
          {!!r.lost?.length && (
            <ul className="mt-1 flex flex-col gap-0.5">
              {r.lost.map((p) => (
                <li key={`${p.symbol}-${p.timeframe}`}
                  className={`text-[11px] ${p.recovered
                    ? "text-success-600 dark:text-success-400" : "text-error-500"}`}>
                  {p.symbol.replace("_USDT", "")} {p.timeframe} —{" "}
                  {p.recovered
                    ? `recovered · ${(p.bars ?? 0).toLocaleString()} bars · stored ${p.when}`
                    : "still lost"}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </li>
  );
}

export default function DownloadHistory({ refreshKey = 0 }: { refreshKey?: number }) {
  const [d, setD] = useState<Payload | null>(null);
  const [tab, setTab] = useState<Tab>("fail");

  const load = useCallback(() => {
    notifyApi.downloadHistory(20).then(setD).catch(() => {});
  }, []);

  // reloads when a job ends, so the row appears without a manual refresh
  useEffect(() => { load(); }, [load, refreshKey]);

  // A STOPPED run is neither: it goes with the errors, because something is
  // unfinished and that is what the operator is looking for in that tab.
  const shown = useMemo(
    () => (d?.rows ?? []).filter((r) => (tab === "ok" ? r.ok : !r.ok)),
    [d, tab],
  );
  // land on the tab that has something in it, so the panel never opens empty
  useEffect(() => {
    if (d && !d.failed && d.ok) setTab("ok");
  }, [d]);

  if (!d || !d.rows.length) return null;

  const counts: Record<Tab, number> = { fail: d.failed, ok: d.ok };

  return (
    <div className="mt-5 rounded-2xl border border-gray-200 bg-white p-5 dark:border-white/[0.05] dark:bg-white/[0.03]">
      <div className="flex flex-wrap items-baseline gap-2">
        <h4 className="text-sm font-semibold text-gray-800 dark:text-white/90">
          Download history
        </h4>
        <span className="text-theme-xs text-gray-500 dark:text-gray-400">
          {d.total} run{d.total === 1 ? "" : "s"}
        </span>
        <div className="ml-auto flex gap-1">
          {TABS.map((t) => (
            <button key={t.id} onClick={() => setTab(t.id)}
              aria-current={tab === t.id ? "true" : undefined}
              className={`rounded-lg px-2.5 py-1 text-theme-xs font-medium ${
                tab === t.id
                  ? t.id === "fail"
                    ? "bg-error-50 text-error-700 dark:bg-error-500/15 dark:text-error-400"
                    : "bg-success-50 text-success-700 dark:bg-success-500/15 dark:text-success-400"
                  : "text-gray-500 hover:bg-gray-50 dark:text-gray-400 dark:hover:bg-white/[0.05]"}`}>
              {t.label} {counts[t.id]}
            </button>
          ))}
        </div>
      </div>

      {shown.length ? (
        <ul className="mt-3 flex flex-col gap-2">
          {shown.map((r) => <Run key={r.ts} r={r} />)}
        </ul>
      ) : (
        <p className="mt-3 text-theme-xs text-gray-500 dark:text-gray-400">
          {tab === "fail"
            ? "no download has failed — every run in this history finished clean"
            : "no download has finished clean yet"}
        </p>
      )}
    </div>
  );
}
