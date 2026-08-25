"use client";
/** Every download this machine has run, newest first, with its OUTCOME.
 *
 * The job's progress file only holds the LAST run, so the history comes from
 * the local event store. The operator asked to see "if it was success" —
 * before this, a finished download left nothing behind that said so.
 */
import { useCallback, useEffect, useState } from "react";
import { DownloadHistory as Payload, notifyApi } from "@/lib/api";

export default function DownloadHistory({ refreshKey = 0 }: { refreshKey?: number }) {
  const [d, setD] = useState<Payload | null>(null);

  const load = useCallback(() => {
    notifyApi.downloadHistory(20).then(setD).catch(() => {});
  }, []);

  // reloads when a job ends, so the row appears without a manual refresh
  useEffect(() => { load(); }, [load, refreshKey]);

  if (!d || !d.rows.length) return null;

  return (
    <div className="mt-5 rounded-2xl border border-gray-200 bg-white p-5 dark:border-white/[0.05] dark:bg-white/[0.03]">
      <div className="flex flex-wrap items-baseline gap-2">
        <h4 className="text-sm font-semibold text-gray-800 dark:text-white/90">
          Download history
        </h4>
        <span className="text-theme-xs text-gray-500 dark:text-gray-400">
          {d.total} run{d.total === 1 ? "" : "s"} · {d.ok} ok
          {d.failed ? <span className="text-error-500"> · {d.failed} failed</span> : null}
        </span>
      </div>

      <ul className="mt-3 flex flex-col gap-1.5">
        {d.rows.map((r) => (
          <li key={r.ts}
            className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 border-b border-gray-50 pb-1.5 last:border-0 dark:border-gray-800/60">
            {/* the outcome, in a word and not only in a colour */}
            <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase ${
              r.stopped
                ? "bg-gray-100 text-gray-500 dark:bg-white/[0.06] dark:text-gray-400"
                : r.ok
                  ? "bg-success-50 text-success-700 dark:bg-success-500/15 dark:text-success-400"
                  : "bg-error-50 text-error-700 dark:bg-error-500/15 dark:text-error-400"}`}>
              {r.stopped ? "stopped" : r.ok ? "success" : "failed"}
            </span>
            <span className="font-mono text-theme-xs text-gray-700 dark:text-gray-300">
              {(r.bars ?? 0).toLocaleString()} bars
            </span>
            <span className="text-theme-xs text-gray-500 dark:text-gray-400">
              {r.pairs ?? 0} pair{r.pairs === 1 ? "" : "s"} · {r.mode}
            </span>
            <span className="ml-auto text-theme-xs text-gray-400 dark:text-gray-500">
              {r.when}
            </span>
            {!r.ok && r.detail && (
              <p className="w-full break-words text-theme-xs text-error-500">{r.detail}</p>
            )}
            {/* is that failure still live? each named pair reads its own store
                file: recovered (with bars and when) or still lost */}
            {!r.ok && !!r.lost?.length && (
              <p className="w-full break-words text-theme-xs">
                {r.lost.map((p, i) => (
                  <span key={`${p.symbol}-${p.timeframe}`}
                    className={p.recovered ? "text-success-600 dark:text-success-400" : "text-error-500"}>
                    {i ? " · " : ""}{p.symbol.replace("_USDT", "")} {p.timeframe} —{" "}
                    {p.recovered
                      ? `recovered · ${(p.bars ?? 0).toLocaleString()} bars · stored ${p.when}`
                      : "still lost"}
                  </span>
                ))}
                {r.unnamed ? (
                  <span className="text-gray-500 dark:text-gray-400">
                    {" "}· {r.unnamed} more error{r.unnamed === 1 ? "" : "s"} not named by that run
                  </span>
                ) : null}
              </p>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
