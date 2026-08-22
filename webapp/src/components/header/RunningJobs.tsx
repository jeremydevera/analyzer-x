"use client";
/** A running job, visible from EVERY screen.
 *
 * Each screen used to poll only its own job on a timer that died when the
 * screen unmounted, so starting a backtest and switching tabs left nothing on
 * screen saying it was still going (operator, 2026-08-21: "i ran a backtest
 * and go to other tab / why was the loading not showing anymore"). The job was
 * never affected — db_jobs runs detached and keeps writing its progress file —
 * the UI just stopped reporting it. This polls one endpoint for all jobs.
 */
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { jobsApi, RunningJob } from "@/lib/api";

const POLL_MS = 4000;

/** where each job's own screen lives, so the chip is a way back to it */
const HREF: Record<string, string> = {
  download: "/candles",
  backtest: "/backtest",
  btupdate: "/backtest",
  stratbt: "/trade",
};

const NAME: Record<string, string> = {
  download: "downloading",
  backtest: "backtesting",
  btupdate: "updating backtests",
  stratbt: "backtesting",
};

export default function RunningJobs() {
  const [running, setRunning] = useState<RunningJob[]>([]);

  const load = useCallback(() => {
    jobsApi.all()
      .then((d) => setRunning(d.running || []))
      .catch(() => { /* the header must never break on a failed poll */ });
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, POLL_MS);
    return () => clearInterval(t);
  }, [load]);

  if (!running.length) return null;

  return (
    <div className="flex items-center gap-2">
      {running.map((j) => (
        <Link key={j.kind} href={HREF[j.kind] ?? "/"}
          title={j.now ? `${NAME[j.kind] ?? j.kind} · ${j.now}` : undefined}
          className="flex items-center gap-2 rounded-full border border-brand-200 bg-brand-50 px-3 py-1.5 text-theme-xs font-medium text-brand-700 transition hover:bg-brand-100 dark:border-brand-500/30 dark:bg-brand-500/10 dark:text-brand-300">
          {/* a moving spinner: a static label cannot say "still working" */}
          <svg className="h-3.5 w-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
            <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3"
                    strokeOpacity="0.25" />
            <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3"
                  strokeLinecap="round" />
          </svg>
          <span>{NAME[j.kind] ?? j.kind}</span>
          {j.pct != null && (
            <span className="font-mono tabular-nums">{j.pct}%</span>
          )}
        </Link>
      ))}
    </div>
  );
}
