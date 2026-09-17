"use client";
/** Which store a screen is showing. On the v2 screens only — a v1 screen with
 *  no badge is the screen the operator has always had, byte for byte. */
import type { StoreName } from "@/lib/api";

export default function StoreBadge({ store }: { store: StoreName }) {
  if (store !== "v2") return null;
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full bg-brand-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-brand-600 dark:bg-brand-500/10 dark:text-brand-400"
      title="Backtest v2: the same signals on the same timeframes, but every win/lose price is checked minute by minute on 1-minute candles, so a candle that touched both prices is no longer a guess">
      v2 · minute-exact exits
    </span>
  );
}
