/**
 * One refresh rule for every panel that shows something that MOVES.
 *
 * Operator, Sep 10, 2026, after a live stop-loss on PSXSTOCK at 8:04pm:
 * *"i want the ui realtime when i lose it should show the winrate lose or
 * what ever currently i need to refresh it"*.
 *
 * Two separate holes made a screen go stale, and a plain `setInterval` only
 * plugs the first:
 *
 * 1. Some panels never re-fetched at all. `TradeHistory` and `PnlPanel`
 *    loaded once and then only retried on FAILURE, so a trade that closed
 *    after the page opened was invisible until a reload — the trade history
 *    is exactly where a closed trade is looked for.
 * 2. A BACKGROUND TAB is throttled by the browser: timers in a hidden tab are
 *    held to about one a minute (Chrome), and a tab hidden long enough gets
 *    frozen entirely. A panel polling every 4 s is a panel polling every 60 s
 *    the moment the operator looks at something else — which is precisely
 *    when they come back and say "it did not update".
 *
 * So: poll while VISIBLE, stop while hidden (a hidden tab's fetch buys
 * nothing and still costs the API), and fetch IMMEDIATELY when the tab is
 * looked at again — which is the instant the answer matters.
 */
import { useEffect, useRef } from "react";

/**
 * Call `load` now, every `ms` while the tab is visible, and again the moment
 * the operator returns to it.
 *
 * `load` is held in a ref, so a component may pass a fresh closure on every
 * render (the usual `() => api.get(page)`) without restarting the timer.
 * Pass `deps` for the values the load depends on — changing one re-runs it at
 * once, which is what a tab switch or a page change should do.
 */
export function useLiveRefresh(load: () => void, ms: number, deps: unknown[] = []) {
  const fn = useRef(load);
  fn.current = load;

  useEffect(() => {
    let dead = false;
    const run = () => { if (!dead && !document.hidden) fn.current(); };
    let timer: ReturnType<typeof setInterval> | undefined;
    const start = () => {
      if (timer !== undefined) return;
      timer = setInterval(run, ms);
    };
    const stop = () => {
      if (timer === undefined) return;
      clearInterval(timer);
      timer = undefined;
    };
    const onVisible = () => {
      if (document.hidden) { stop(); return; }
      run();               // the answer they came back for, not in 4 seconds
      start();
    };
    run();
    if (!document.hidden) start();
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", onVisible);
    return () => {
      dead = true;
      stop();
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", onVisible);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ms, ...deps]);
}
