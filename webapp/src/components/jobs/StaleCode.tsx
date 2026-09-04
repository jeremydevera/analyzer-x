"use client";
/** Which long-running process is still holding OLD CODE.
 *
 * Operator, Sep 04, 2026: *"SO WHAT'S NOT UPDATED?"* then *"I DONT WANT THIS
 * BUG FIX THIS"*.
 *
 * A process keeps the code it started with, and no screen said so. The
 * backtest job (started Sep 03 3:30pm) ran 32 hours on 3 of 11 cores after the
 * commit that lets the worker window grow — a pool cannot be resized, so it
 * could never pick it up. The live runner (Sep 04 11:04am) went on holding the
 * loss-cap version that writes the KILL file and EXITS, taking the paper book
 * down with it, two minutes after the fix landed. The only way anyone found
 * out was comparing process start times to `git log` by hand.
 *
 * THREE states per process, never two: stale, current, or unknown. A silent
 * "current" when git cannot be read is exactly how a 32-hour stale job looked
 * healthy.
 */
import { useEffect, useState } from "react";
import { api, Staleness } from "@/lib/api";

export default function StaleCode() {
  const [d, setD] = useState<Staleness | null>(null);

  useEffect(() => {
    const tick = () => api.staleness().then(setD).catch(() => setD(null));
    tick();
    const t = setInterval(tick, 60_000);
    return () => clearInterval(t);
  }, []);

  // nothing to say when every process is current — the row is for problems
  if (!d || (!d.stale_count && !d.unknown_count)) return null;

  const stale = d.processes.filter((p) => p.stale);
  const unknown = d.processes.filter((p) => p.stale === null);

  return (
    <div className={`mt-3 rounded-lg border px-3 py-2 text-theme-xs ${
      stale.length
        ? "border-warning-500/40 bg-warning-50 dark:bg-warning-500/10"
        : "border-gray-200 bg-gray-50 dark:border-white/[0.05] dark:bg-white/[0.03]"}`}>
      <p className={stale.length
        ? "font-medium text-warning-700 dark:text-warning-400"
        : "text-gray-500 dark:text-gray-400"}>
        {/* NAMED, never "1 process is stale" — being told a count is what made
            the operator ask which one. */}
        {stale.length
          ? `${stale.length} running process${stale.length === 1 ? "" : "es"} still on old code`
          : `${unknown.length} process${unknown.length === 1 ? "" : "es"} of unknown code age`}
      </p>
      <ul className="mt-1 flex flex-col gap-0.5 text-gray-600 dark:text-gray-300">
        {stale.map((p) => (
          <li key={p.kind}>
            <b className="uppercase">{p.kind}</b>{" "}
            — {p.commits_behind} commit{p.commits_behind === 1 ? "" : "s"} behind,
            started {p.started}. Restart it to pick them up.
          </li>
        ))}
        {unknown.map((p) => (
          <li key={p.kind} className="text-gray-500 dark:text-gray-400">
            <b className="uppercase">{p.kind}</b> — {p.why}
          </li>
        ))}
      </ul>
      {d.head && (
        <p className="mt-1 text-gray-400 dark:text-gray-500">
          newest commit {d.head.sha} · {d.head.when}
        </p>
      )}
    </div>
  );
}
