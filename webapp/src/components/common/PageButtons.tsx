"use client";
/** THE AUTO TRADE PAGER, for a list paged by the server (operator, Oct 02,
 *  2026: "in forecast, make it paginated just like in auto trade"). The same
 *  buttons, sizes and colours as Positions and the Watcher on Auto Trade:
 *  prev, the page numbers around this one with … for the distance
 *  (lib/pager.pageWindow), next, and "of N". Nothing is drawn when the list
 *  fits on one page. `busy` greys every button while a page is being worked
 *  out (Backtest a room re-measures on each page). */
import { pageWindow } from "@/lib/pager";

const pageNum = "h-8 min-w-8 rounded-lg border px-2 text-theme-xs tabular-nums";
const pageBtn = "h-8 rounded-lg border border-gray-300 px-2 text-theme-xs text-gray-600 "
  + "disabled:opacity-40 dark:border-gray-700 dark:text-gray-300";

export default function PageButtons({ cur, pages, goto, what, busy = false }: {
  cur: number; pages: number; goto: (n: number) => void; what: string; busy?: boolean;
}) {
  if (pages <= 1) return null;
  const go = (n: number) => goto(Math.min(Math.max(1, n), pages));
  return (
    <div className="mt-2 flex flex-wrap items-center gap-1">
      <button type="button" onClick={() => go(cur - 1)} disabled={busy || cur <= 1} className={pageBtn}>prev</button>
      {pageWindow(cur, pages).map((n, i) => n == null ? (
        <span key={`gap${i}`} aria-hidden className="px-1 text-theme-xs text-gray-400">…</span>
      ) : (
        <button type="button" key={n} onClick={() => go(n)} disabled={busy} aria-label={`${what} page ${n}`}
          aria-current={n === cur ? "page" : undefined}
          className={`${pageNum} ${n === cur
            ? "border-brand-500 bg-brand-500 font-semibold text-white"
            : "border-gray-300 text-gray-600 hover:border-brand-400 dark:border-gray-700 dark:text-gray-300"}`}>
          {n}
        </button>
      ))}
      <button type="button" onClick={() => go(cur + 1)} disabled={busy || cur >= pages} className={pageBtn}>next</button>
      <span className="text-theme-xs text-gray-500 dark:text-gray-400">of {pages}</span>
    </div>
  );
}
