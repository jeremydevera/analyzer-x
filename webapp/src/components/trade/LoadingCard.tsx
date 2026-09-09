"use client";
/** ONE spinner, and under it the names of what is still loading.
 *
 * The operator's own design (Sep 09, 2026): *"show a loading spinning icon
 * thats the simplest, then under that icon show whats being loaded so im
 * aware like — Loading backtesting / Then loading coins / Loading etc"*.
 *
 * A name that has waited past LATE_MS turns red and says it is retrying —
 * a wait is honest for a while, then it is a failure wearing a spinner
 * (fail loudly, never quietly). The card removes itself when everything
 * has loaded, and a 1s tick keeps the late check honest even when no
 * panel re-renders.
 */
import { useEffect, useState } from "react";
import { LATE_MS, pending, subscribe } from "@/lib/loading";

export default function LoadingCard() {
  const [, setTick] = useState(0);
  useEffect(() => {
    const un = subscribe(() => setTick((t) => t + 1));
    const t = setInterval(() => setTick((x) => x + 1), 1_000);
    return () => { un(); clearInterval(t); };
  }, []);

  const waitlist = pending();
  if (!waitlist.length) return null;

  return (
    <div className="rounded-2xl border border-gray-200 bg-white p-4 dark:border-white/[0.05] dark:bg-white/[0.03]">
      <div className="flex items-center gap-3">
        <span aria-hidden
              className="h-5 w-5 shrink-0 animate-spin rounded-full border-2 border-gray-300 border-t-brand-500 dark:border-gray-600 dark:border-t-brand-400" />
        <span className="text-sm font-medium text-gray-700 dark:text-gray-200">
          loading the terminal
        </span>
      </div>
      <ul className="mt-2 flex flex-col gap-0.5 pl-8">
        {waitlist.map(({ name, waitedMs }) => (
          <li key={name}
              className={`text-theme-xs ${waitedMs > LATE_MS
                ? "text-error-500"
                : "text-gray-500 dark:text-gray-400"}`}>
            {waitedMs > LATE_MS
              ? `${name} — still not loading after ${Math.round(waitedMs / 1000)}s, retrying`
              : `loading ${name}…`}
          </li>
        ))}
      </ul>
    </div>
  );
}
