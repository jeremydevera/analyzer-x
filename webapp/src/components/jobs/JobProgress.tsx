"use client";
/**
 * One job's progress. Shared by every screen that starts a job, so they
 * cannot drift.
 *
 * Two rules the first version got wrong:
 *
 * 1. A FINISHED job keeps its progress file forever, so `finished && !running`
 *    rendered a bar on every visit — the operator saw a green bar from a run
 *    two days earlier and asked why it would not go away. A finished result is
 *    only news for a few minutes, and it is dismissible.
 * 2. "stopped by you" is NOT success. It used to paint a full green bar
 *    because only `error` was checked, which told the operator a stopped
 *    backtest had completed.
 */
import { useEffect, useState } from "react";
import { JobStatus } from "@/lib/api";

const FRESH_SECONDS = 600;   // a finished result stops being news after 10 min

export default function JobProgress({ s, label }: { s: JobStatus | null; label?: string }) {
  const [dismissed, setDismissed] = useState<number | null>(null);
  useEffect(() => {
    if (s?.running) setDismissed(null);   // a new run clears an old dismissal
  }, [s?.running]);

  if (!s) return null;
  const age = s.finished ? Date.now() / 1000 - s.finished : Infinity;
  const stale = !s.running && age > FRESH_SECONDS;
  const hidden = !s.running && s.finished != null && dismissed === s.finished;
  if (!s.running && (stale || hidden || !s.finished)) return null;

  // two decimals, from the job's EXACT figure when it publishes one — `done`
  // is a whole number, so done/total alone could not show them
  const pct = s.pct != null
    ? Math.min(100, s.pct)
    : s.total ? Math.min(100, (100 * (s.done ?? 0)) / s.total) : 0;
  const state = s.error ? "error" : s.stopped ? "stopped" : s.running ? "running" : "done";
  const bar = { error: "bg-error-500", stopped: "bg-warning-400",
                running: "bg-brand-500", done: "bg-success-500" }[state];
  // a stopped or failed job shows how far it actually got — never a full bar
  const width = state === "done" ? 100 : Math.max(pct, 3);

  return (
    <div className="mt-3">
      <div className="mb-1 flex items-start justify-between gap-3 text-theme-xs text-gray-500 dark:text-gray-400">
        <span className={state === "error" ? "text-error-500" : state === "stopped" ? "text-warning-600" : ""}>
          {label ? <b className="mr-1">{label}</b> : null}
          {s.running ? (s.now ?? "running…")
            : s.error ? `failed: ${s.error}`
            : (s.note || (state === "stopped" ? "stopped" : "finished"))}
        </span>
        <span className="flex shrink-0 items-center gap-2 whitespace-nowrap">
          {s.running || s.stopped ? (
            <b className="tabular-nums text-gray-700 dark:text-gray-200">{pct.toFixed(2)}%</b>
          ) : null}
          {s.total ? `${s.done ?? 0}/${s.total}` : null}
          {s.bars_stored != null && ` · ${s.bars_stored.toLocaleString()} bars`}
          {s.rows != null && ` · ${s.rows.toLocaleString()} rows`}
          {!s.running && (
            <button onClick={() => setDismissed(s.finished ?? 0)} aria-label="dismiss"
              className="rounded px-1 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200">
              ×
            </button>
          )}
        </span>
      </div>
      <div className="h-2 w-full rounded-full bg-gray-200 dark:bg-gray-800">
        <div className={`h-2 rounded-full ${bar}`} style={{ width: `${width}%` }} />
      </div>

      {/* PER CORE. The overall bar counts finished PAIRS, so on a long pair it
          can sit still for minutes and look stuck. These say which pair each
          core has and how far into it — the operator asked to see the machine
          really working. */}
      {s.running && !!s.workers?.length && (
        <div className="mt-2">
          <p className="mb-1 text-[10px] uppercase tracking-wide text-gray-400 dark:text-gray-500">
            {s.workers.length} of {s.cores ?? s.workers.length} core
            {(s.cores ?? s.workers.length) === 1 ? "" : "s"} working
          </p>
          <div className="flex flex-col gap-1">
            {s.workers.map((w, i) => {
              // "done" is a worker's LAST line before it picks up the next
              // pair, not an idle core — the reader now drops a line that
              // stops being written, so anything here is a living worker.
              const idle = w.state === "done" || w.state === "no new bars";
              return (
                <div key={w.pid ?? w.slot ?? i} className="flex items-center gap-2">
                  <span className="w-10 shrink-0 font-mono text-[10px] text-gray-400 dark:text-gray-500">
                    #{w.core ?? i}
                  </span>
                  <span className="w-24 shrink-0 truncate text-[10px] text-gray-600 dark:text-gray-300">
                    {w.pair ?? "—"}
                  </span>
                  <span className="h-1.5 min-w-0 flex-1 rounded-full bg-gray-200 dark:bg-gray-800">
                    <span
                      className={`block h-1.5 rounded-full ${idle ? "bg-success-500" : "bg-brand-500"}`}
                      style={{ width: `${Math.max(w.pct ?? 0, 2)}%` }} />
                  </span>
                  <span className="w-14 shrink-0 text-right font-mono text-[10px] tabular-nums text-gray-500 dark:text-gray-400">
                    {idle ? "saving" : `${(w.pct ?? 0).toFixed(2)}%`}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
      {!s.running && (
        <p className="mt-1 text-[10px] text-gray-400">
          {state === "stopped" ? "stopped" : state === "error" ? "failed" : "finished"}{" "}
          {s.finished ? new Date(s.finished * 1000).toLocaleString() : ""} · this clears itself
        </p>
      )}
    </div>
  );
}
