"use client";
/** A panel's error line that knows the difference between LOADING and BROKEN.
 *
 * Sep 09, 2026: an API restart's ~10 dark seconds put a red ApiError under
 * every panel at once, and the screen read as "your trading is broken" while
 * nothing was wrong. While a panel has never loaded and the wait is young,
 * its failure is a LOADING state (the card at the top is already naming it);
 * red is for a failure that persists past LATE_MS, or one that arrives AFTER
 * data was on screen — those are real news.
 */
import { useEffect, useRef, useState } from "react";
import { LATE_MS } from "@/lib/loading";

export default function PanelStatus({ err, loaded, className }: {
  err: string;
  /** has this panel EVER shown data? an error after data is always red */
  loaded: boolean;
  className?: string;
}) {
  const firstErrAt = useRef(0);
  const [, setTick] = useState(0);
  if (err && !firstErrAt.current) firstErrAt.current = Date.now();
  if (!err && firstErrAt.current) firstErrAt.current = 0;
  const young = !!err && !loaded && Date.now() - firstErrAt.current < LATE_MS;
  // flip young -> late on our own clock, even if no retry re-renders us
  useEffect(() => {
    if (!young) return;
    const left = LATE_MS - (Date.now() - firstErrAt.current) + 250;
    const t = setTimeout(() => setTick((x) => x + 1), left);
    return () => clearTimeout(t);
  }, [young, err]);

  if (!err) return null;
  if (young) return null;   // the LoadingCard is naming it
  return <p className={className ?? "px-5 pt-2 text-theme-sm text-error-500"}>{err}</p>;
}
