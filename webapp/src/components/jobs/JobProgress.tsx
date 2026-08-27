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
import { api, JobStatus, SysLoad, fmtWhen } from "@/lib/api";

const FRESH_SECONDS = 600;   // a finished result stops being news after 10 min

/** What the machine is doing, beside the bar that is doing it.
 *
 * There is no temperature here: macOS exposes a die temperature only to root
 * on Apple Silicon (powermetrics refuses the SMC sampler otherwise), and a
 * figure inferred from load would be a guess wearing a measurement's clothes.
 * What IS real is CPU busy, load per core, and whether the OS is throttling.
 */
function MachineLoad() {
  const [sys, setSys] = useState<SysLoad | null>(null);
  useEffect(() => {
    const tick = () => api.system().then(setSys).catch(() => {});
    tick();
    const t = setInterval(tick, 5000);
    return () => clearInterval(t);
  }, []);
  if (!sys) return null;
  const hot = sys.load_per_core >= 1.5;
  const th = sys.thermal;
  return (
    <span className="flex shrink-0 items-center gap-2 whitespace-nowrap text-[10px]">
      <span className={sys.busy != null && sys.busy > 90 ? "text-warning-600" : "text-gray-500 dark:text-gray-400"}
        title="how much of every core is busy right now, across the whole Mac">
        CPU {sys.busy != null ? `${sys.busy.toFixed(1)}%` : "—"}
      </span>
      <span className={hot ? "text-warning-600" : "text-gray-500 dark:text-gray-400"}
        title={`${sys.load1} processes wanted to run across ${sys.cores} cores. Above 1.00x per core means work is queueing.`}>
        load {sys.load1.toFixed(2)}/{sys.cores} ({sys.load_per_core.toFixed(2)}x)
      </span>
      {/* free MEMORY, beside the CPU numbers: the operator's PC froze twice on
          Aug 27, 2026 while a sweep ran unattended and nothing on the page
          said how much room was left. "unknown" is shown as unknown, never as
          0 GB free. */}
      <span className={sys.ram_free_gb != null && sys.ram_free_gb < 2
                         ? "text-error-500"
                         : sys.ram_free_gb != null && sys.ram_free_gb < 3
                           ? "text-warning-600" : "text-gray-500 dark:text-gray-400"}
        title={sys.ram_kind === "measured"
          ? `${sys.ram_free_gb} GB of ${sys.ram_total_gb} GB free. A sweep keeps 2 GB for the desktop and takes about 0.2 GB per pair at 1h/4h, 0.5 GB at 15m/30m.`
          : "this machine does not report its memory, so the sweep is not limited by it"}>
        RAM {sys.ram_kind === "measured" && sys.ram_free_gb != null
          ? `${sys.ram_free_gb.toFixed(1)}/${(sys.ram_total_gb ?? 0).toFixed(0)} GB free`
          : "—"}
      </span>
      <span className={th.throttled ? "text-error-500" : "text-gray-400"}
        title={th.why || `macOS reports the CPU running at ${th.speed_limit}% of full speed`}>
        {th.throttled
          ? `THROTTLING ${th.speed_limit}%`
          : th.available ? "no throttling" : "temp: root only"}
      </span>
    </span>
  );
}

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
          {s.running && <MachineLoad />}
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
            {/* WHY, when the run took fewer cores than the machine has: "4 of
                11" on its own reads as a broken machine. */}
            {s.cores_why ? (
              <span className="ml-2 normal-case tracking-normal text-warning-600">
                &middot; {s.cores_why}
              </span>
            ) : s.cores_offered && s.cores && s.cores_offered > s.cores ? (
              <span className="ml-2 normal-case tracking-normal text-gray-400">
                &middot; {s.cores_offered} offered
              </span>
            ) : null}
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
          {s.finished ? fmtWhen(s.finished) : ""} · this clears itself
        </p>
      )}
    </div>
  );
}
