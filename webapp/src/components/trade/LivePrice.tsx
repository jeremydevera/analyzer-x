"use client";
/** The runner's websocket, on screen — ONE implementation, two tables.
 *
 * `Live` and `FeedBadge` started inside PositionsPanel. The strategies grid
 * needs exactly the same two things (operator, `Sep 16, 2026`: "show me
 * proof, show the live price in each row"), and this repo has paid five
 * times for a second copy of a thing that drifts, so they moved here instead
 * of being pasted.
 */
import type { FeedStatus } from "@/lib/api";

/** The last price MEXC PUSHED to the runner for this contract.
 *
 *  Age is printed beside it on purpose. A number with no age cannot be told
 *  apart from a number that stopped arriving, and "realtime" is exactly the
 *  claim a reader needs to be able to check (label-must-match-data). Over
 *  ten seconds old stops being green.
 */
export function Live({ sym, feed }: { sym: string; feed: FeedStatus | null }) {
  const row = feed?.prices?.find((p) => p.symbol === sym);
  if (!feed?.connected || !row || row.price == null) {
    return <span className="text-gray-400" title={
      feed?.why ?? (feed?.connected ? "no tick for this contract yet"
                                    : "the runner's websocket is not connected")
    }>—</span>;
  }
  const fresh = row.age < 10;
  return (
    <span title={`pushed by MEXC ${row.age.toFixed(1)}s ago · ${row.ticks ?? 0} ticks held`}>
      <span className={fresh ? "font-medium text-gray-800 dark:text-white/90"
                             : "text-gray-400"}>{row.price}</span>
      <span className={`ml-1 text-[10px] ${fresh ? "text-success-600" : "text-warning-500"}`}>
        {row.age < 1 ? "now" : `${Math.round(row.age)}s`}
      </span>
    </span>
  );
}

/** Proof, not decoration: the socket the runner is actually holding. */
export function FeedBadge({ feed }: { feed: FeedStatus | null }) {
  if (!feed) return null;
  const on = feed.connected;
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] font-medium ${
      on ? "bg-success-50 text-success-600 dark:bg-success-500/10"
         : "bg-warning-50 text-warning-600 dark:bg-warning-500/10"}`}
      title={on
        ? `${feed.url} · ${feed.messages ?? 0} messages · ${feed.connects ?? 1} connection(s) · `
          + `${(feed.tracking ?? []).length} contract(s) · ${(feed.klines ?? []).length} candle stream(s)`
          + (feed.logged_in ? " · signed in for live fills" : "")
        : (feed.why ?? feed.last_error ?? "not connected")}>
      <span className={`h-1.5 w-1.5 rounded-full ${on ? "bg-success-500" : "bg-warning-500"}`} />
      {on ? `websocket live · ${feed.messages ?? 0} pushes` : "websocket down"}
    </span>
  );
}
