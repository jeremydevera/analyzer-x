"use client";
/** A SKILL ROOM'S PANEL, in place of the watcher and the keys (operator, Nov 10, 2026: three
 *  practice rooms trade Backtest v4's Claude-skill strategies exactly as their backtest did, by a
 *  follower - tradingagents/v4_follow.py - with no runner and no watcher).
 *
 *  Every word and number is the server's (GET /api/trade/v4-follow): the rule in words, today's
 *  switched-on list (paged by the server, ten at a time), the daily refresh, and yesterday's
 *  agreement with the backtest. Dates are fmtWhen, never a hand-rolled stamp.
 */
import { useCallback, useState } from "react";
import { fmtWhen, V4Follow } from "@/lib/api";
import { useRoomApis } from "@/lib/room";
import { useLiveRefresh } from "@/lib/live";
import PageButtons from "@/components/common/PageButtons";
import { Table, TableBody, TableCell, TableHeader, TableRow } from "@/components/ui/table";

const th = "px-2 py-2 text-left text-theme-xs font-medium text-gray-500 dark:text-gray-400 whitespace-nowrap";
const td = "whitespace-nowrap px-2 py-2 text-theme-sm tabular-nums text-gray-700 dark:text-gray-300";

/** The line that says what the follower's trades cost - the same on every row. */
export const COST_LINE = "Every trade pays its coin's usual gap, not its own minute's order book (100% typical cost) · no trade is refused by the runner's cost check · no order is placed";

export default function V4FollowPanel() {
  const { tradeApi } = useRoomApis();
  const [page, setPage] = useState(1);
  const [d, setD] = useState<V4Follow | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setBusy(true);
    return tradeApi.v4Follow(page)
      .then((x) => { setD(x); setErr(""); })
      .catch((e) => setErr(String(e)))
      .finally(() => setBusy(false));
  }, [tradeApi, page]);
  useLiveRefresh(load, 30_000, [page]);

  const daily = d?.daily;
  const ag = d?.agreement;
  return (
    <div className="rounded-2xl border border-gray-200 bg-white p-4 dark:border-white/[0.05] dark:bg-white/[0.03]">
      <h3 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">Follows Backtest v4</h3>
      {err && <p className="mt-2 text-theme-xs text-error-500">{err}</p>}
      {!d && !err && <p className="mt-2 text-theme-xs text-gray-400">reading…</p>}
      {d && d.follows == null && (
        <p className="mt-2 text-theme-xs text-gray-400">this room has no follower: it is traded by its own runner</p>
      )}
      {d && d.follows && (
        <>
          <p className="mt-1 text-theme-sm text-gray-600 dark:text-gray-300">{d.rule_words}</p>
          {d.picker && (
            <p className="mt-1 text-theme-xs text-gray-500 dark:text-gray-400">
              {`The daily picker gave this room #${d.picker.rule_id}${d.picker.since ? ` on ${d.picker.since}` : ""}`}
              {d.picker.why ? ` — ${d.picker.why}.` : "."}
              {` It keeps a rule while it passes, and swaps or switches it off when it stops${d.picker.enabled ? "" : " (the picker is switched off: rooms keep what they follow now)"}.`}
            </p>
          )}
          <p className="mt-2 text-theme-xs text-gray-500 dark:text-gray-400">{COST_LINE}</p>

          {/* the day's refresh sentence */}
          {daily && (
            <p className="mt-2 text-theme-xs text-gray-500 dark:text-gray-400">
              {`Backtest v4 is refreshed every day — ${daily.words}`}
            </p>
          )}
          {d.fallback_words && (
            <p className="mt-1 text-theme-xs text-warning-600 dark:text-warning-400">{d.fallback_words}</p>
          )}

          {/* an empty list before today's has landed is "not made yet", never "nothing passes" */}
          <p className="mt-4 text-theme-xs font-semibold text-gray-700 dark:text-gray-300">
            Switched on today{d.today_landed === false ? "" : ` · ${(d.total_on ?? 0).toLocaleString()}`}
            {busy && <span className="ml-2 font-normal text-gray-400">loading…</span>}
          </p>
          {d.today_landed === false ? (
            <p className="mt-1 text-theme-xs text-gray-400">
              {`today's list has not landed yet (${d.today_why ?? "the daily refresh has not made it yet"})`}
            </p>
          ) : (d.total_on ?? 0) === 0 ? (
            <p className="mt-1 text-theme-xs text-gray-400">
              no strategy passes this rule today, so the room opens nothing
            </p>
          ) : (
            <div className="mt-1 max-w-full overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableCell isHeader className={th}>ID</TableCell>
                    <TableCell isHeader className={th}>Coin</TableCell>
                    <TableCell isHeader className={th}>Timeframe</TableCell>
                    <TableCell isHeader className={th}>Strategy</TableCell>
                    <TableCell isHeader className={th}>
                      {d.window_days != null ? `Last ${d.window_days} days: Trades` : "Trades"}
                    </TableCell>
                    <TableCell isHeader className={th}>Wins</TableCell>
                    <TableCell isHeader className={th}>Win rate</TableCell>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(d.switched_on ?? []).map((r) => (
                    <TableRow key={r.id}>
                      <TableCell className={`${td} font-mono text-brand-500`}>#{r.id}</TableCell>
                      <TableCell className={td}>{r.coin}</TableCell>
                      <TableCell className={td}>{r.tf}</TableCell>
                      <TableCell className={td}>{r.label}</TableCell>
                      <TableCell className={td}>{r.n}</TableCell>
                      <TableCell className={td}>{r.wins}</TableCell>
                      <TableCell className={td}>{r.win_rate == null ? "—" : `${r.win_rate.toFixed(1)}%`}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
          <PageButtons cur={d.page ?? 1} pages={d.pages ?? 1} goto={setPage} what="switched on" busy={busy} />

          {/* yesterday's agreement with the backtest */}
          {/* the UTC day it checked, named by when it ENDED (its start in this PC's time reads as
              the day before); "Yesterday's" only when it is */}
          <p className="mt-4 text-theme-xs font-semibold text-gray-700 dark:text-gray-300">
            {ag?.yesterday === false ? "Latest check" : "Yesterday's check"}
            {ag?.ended_s != null ? ` (the day that ended ${fmtWhen(ag.ended_s)})` : ""}
          </p>
          {!ag && <p className="mt-1 text-theme-xs text-gray-400">not checked yet: the first check runs after the first daily refresh</p>}
          {ag?.error && <p className="mt-1 text-theme-xs text-error-500">not checked: {ag.error}</p>}
          {ag && !ag.error && (
            <>
              <p className="mt-1 text-theme-sm text-gray-700 dark:text-gray-300">
                {ag.of === 0
                  ? "no trades closed that day"
                  : `${ag.same} of ${ag.of} trades the same as the backtest · $${(ag.dollars_apart ?? 0).toFixed(2)} apart`}
              </p>
              {((ag.only_practice?.length ?? 0) + (ag.only_backtest?.length ?? 0)) > 0 && (
                <p className="mt-1 max-h-24 overflow-y-auto break-words text-theme-xs text-gray-500 dark:text-gray-400">
                  not the same: {[...(ag.only_practice ?? []), ...(ag.only_backtest ?? [])].join(", ")}
                </p>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
