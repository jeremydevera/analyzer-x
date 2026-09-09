"use client";
/** The screen stays BLURRED until everything has loaded — on top of the blur,
 * one spinner and the names of what is still loading.
 *
 * The operator's design, refined twice (Sep 09, 2026): *"show a loading
 * spinning icon thats the simplest, then under that icon show whats being
 * loaded so im aware"*, then *"make the screen blurred until its fully
 * loaded meaning only show the loading icon then the sentence loading
 * candles or loading this etc"*.
 *
 * The blur DROPS once any name has waited past LATE_MS: at that point the
 * wait is a failure wearing a spinner, the loaded panels are usable, and the
 * stuck name shows red both here and in its own panel. A broken endpoint
 * must never lock the whole terminal behind frosted glass.
 */
import { useEffect, useState } from "react";
import { LATE_MS, pending, subscribe } from "@/lib/loading";

/** the live waitlist, re-read on every report and once a second (the 1s tick
 *  keeps the late check honest even when no panel re-renders) */
export function useWaitlist() {
  const [, setTick] = useState(0);
  useEffect(() => {
    const un = subscribe(() => setTick((t) => t + 1));
    const t = setInterval(() => setTick((x) => x + 1), 1_000);
    return () => { un(); clearInterval(t); };
  }, []);
  return pending();
}

export default function LoadingOverlay(
  { waitlist }: { waitlist: { name: string; waitedMs: number }[] },
) {
  if (!waitlist.length) return null;
  // the WRAPPER is click-through: when a late name drops the blur, the
  // loaded panels underneath must be usable — only the card itself is solid
  return (
    <div className="pointer-events-none absolute inset-0 z-20 flex items-start justify-center pt-24">
      <div className="pointer-events-auto flex flex-col items-center gap-3 rounded-2xl border border-gray-200 bg-white/95 px-8 py-6 shadow-lg dark:border-white/[0.08] dark:bg-gray-900/95">
        <span aria-hidden
              className="h-8 w-8 animate-spin rounded-full border-[3px] border-gray-300 border-t-brand-500 dark:border-gray-600 dark:border-t-brand-400" />
        <div className="flex flex-col items-center gap-0.5">
          {waitlist.map(({ name, waitedMs }) => (
            <span key={name}
                  className={`text-theme-sm ${waitedMs > LATE_MS
                    ? "font-medium text-error-500"
                    : "text-gray-600 dark:text-gray-300"}`}>
              {waitedMs > LATE_MS
                ? `${name} — still not loading after ${Math.round(waitedMs / 1000)}s, retrying`
                : `loading ${name}…`}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
