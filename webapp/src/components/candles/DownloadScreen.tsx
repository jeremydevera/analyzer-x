"use client";
/**
 * Download candles onto this PC. Its own screen because the Backtest screen
 * is for backtesting — mixing the two put a multi-hour download one click
 * away from a grid run.
 *
 * The job is detached: switching screens or closing the browser does not stop
 * it, because the truth lives in the job's progress file, not in this
 * component.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { api, JobStatus } from "@/lib/api";
import Button from "@/components/ui/button/Button";
import Badge from "@/components/ui/badge/Badge";
import CoinPicker from "@/components/backtest/CoinPicker";
import JobProgress from "@/components/jobs/JobProgress";
import DownloadHistory from "@/components/candles/DownloadHistory";
import StoragePanel from "@/components/backtest/StoragePanel";

const TFS = ["15m", "30m", "1h", "4h", "1d"];

export default function DownloadScreen() {
  const [coins, setCoins] = useState<string[]>([]);
  const [gaps, setGaps] = useState<Awaited<ReturnType<typeof api.candleGaps>> | null>(null);
  const [lost, setLost] = useState<Awaited<ReturnType<typeof api.candleLost>> | null>(null);
  const [whole, setWhole] = useState<Awaited<ReturnType<typeof api.candleCompleteness>> | null>(null);
  // ONE definition of pending, from the route — never counted in this
  // component, which is how the button and the Pending tab came to disagree.
  const [pending, setPending] = useState<Awaited<ReturnType<typeof api.candlePending>> | null>(null);
  const [tfs, setTfs] = useState<string[]>(["15m", "30m", "1h", "4h"]);
  const [dl, setDl] = useState<JobStatus | null>(null);
  const [err, setErr] = useState("");
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const poll = useCallback(() => {
    api.jobStatus("download").then(setDl).catch(() => {});
  }, []);
  const scanGaps = useCallback(() => {
    // this walks EVERY stored pair's file, so it runs on arrival and after a
    // job ends — never on the 4-second job poll
    api.candleGaps().then(setGaps).catch(() => {});
    // the lost list is rewritten by every download job, so it refreshes on
    // the same schedule: arrival, every minute, and when a job ends
    api.candleLost().then(setLost).catch(() => {});
    api.candleCompleteness().then(setWhole).catch(() => {});
    api.candlePending().then(setPending).catch(() => {});
  }, []);
  useEffect(() => {
    poll();
    scanGaps();
    timer.current = setInterval(poll, 4000);
    const slow = setInterval(scanGaps, 60000);
    return () => { if (timer.current) clearInterval(timer.current); clearInterval(slow); };
  }, [poll, scanGaps]);
  const wasRunning = useRef(false);
  useEffect(() => {
    if (wasRunning.current && !dl?.running) scanGaps();   // a job just ended
    wasRunning.current = !!dl?.running;
  }, [dl?.running, scanGaps]);

  /** UPDATE = fill the gap since each stored pair's LAST BAR. No coin needs
   * picking: the pairs come from the store, so a store filled on 28 July and
   * updated on 21 August fetches exactly the bars between. */
  const update = async () => {
    setErr("");
    if (!confirm(`Update ${gaps?.pairs ?? 0} stored pair(s)?\n\nOnly the bars printed since each pair's last stored bar are fetched — nothing is downloaded again.`)) return;
    try { await api.jobStart("download", { mode: "update" }); poll(); }
    catch (e) { setErr(String(e)); }
  };

  /** RESOLVE PENDING = every fixable pending in one run: the pairs the last
   * run LOST (first — they are what the button was pressed for), the pairs the
   * store has never had, and every pair behind by more than a bar.
   *
   * Operator, Sep 04, 2026: *"IF I CLICK THIS I WANT TO RESOLVE PENDINGS"*.
   * Each kind used to need a different button, and UPDATE was disabled when
   * the store had no gaps — so a lost-only pending had no enabled button at
   * all. */
  const resolve = async () => {
    setErr("");
    const n = pending?.count ?? 0;
    if (!confirm(
      `Resolve ${n.toLocaleString()} pending thing(s)?

` +
      `${(pending?.lost ?? 0).toLocaleString()} the last run lost (fetched first)
` +
      `${(pending?.missing ?? 0).toLocaleString()} the store has never had
` +
      `${(pending?.behind ?? 0).toLocaleString()} behind by more than a bar

` +
      `Only the bars printed since each pair's last stored bar are fetched.` +
      // The QUEUE is longer than the COUNT: a pair on a contract MEXC dropped
      // gets one confirming attempt, because the contract list is filtered and
      // a stale answer must not delete work — but it is not pending, since
      // nothing can fix it. Both numbers are shown rather than one standing in
      // for the other (label-must-match-data).
      ((pending?.queue ?? 0) > n
        ? `

${(pending!.queue - n).toLocaleString()} more pair(s) on delisted contracts are attempted once to confirm, so ${pending!.queue.toLocaleString()} pairs are touched in total. They are not counted as pending — nothing can fix them.`
        : "") +
      ((pending?.unfixable ?? 0) > 0
        ? `

${(pending?.unfixable ?? 0).toLocaleString()} pair(s) cannot be fixed by any run (delisted, or the venue serves no candles).`
        : ""))) return;
    try { await api.jobStart("download", { mode: "resolve" }); poll(); }
    catch (e) { setErr(String(e)); }
  };

  /** RETRY FAILED = only the pairs the last run gave up on
   * (db_download.lost.json). Nothing else is touched. */
  const retry = async () => {
    setErr("");
    try { await api.jobStart("download", { mode: "retry" }); poll(); }
    catch (e) { setErr(String(e)); }
  };

  const start = async () => {
    setErr("");
    if (coins.length > 50 &&
        !confirm(`${coins.length} contracts × ${tfs.length} timeframe(s).\n\nA first download this size takes hours. It keeps whatever finishes, and you can stop it at any point.`)) return;
    try { await api.jobStart("download", { coins, tfs }); poll(); }
    catch (e) { setErr(String(e)); }
  };

  return (
    <div className="flex flex-col gap-5">
      <div className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-white/[0.05] dark:bg-white/[0.03]">
        <h3 className="text-base font-semibold text-gray-800 dark:text-white/90">Download candles</h3>
        <p className="mb-4 text-theme-xs text-gray-500 dark:text-gray-400">
          Fills this PC&apos;s store — the candles every backtest reads. Runs detached: leaving this
          screen or closing the browser does not stop it. After the first fill, only new bars are fetched.
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-theme-xs text-gray-500 dark:text-gray-400">Coins</label>
            <CoinPicker value={coins} onChange={setCoins} />
          </div>
          <div>
            <label className="mb-1 block text-theme-xs text-gray-500 dark:text-gray-400">Timeframes</label>
            <div className="flex flex-wrap gap-2 pt-1.5">
              {TFS.map((t) => (
                <button key={t}
                  onClick={() => setTfs((cur) => cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t])}
                  className={`rounded-full px-3 py-1 text-theme-xs font-medium ${tfs.includes(t)
                    ? "bg-brand-500 text-white" : "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300"}`}>
                  {t}
                </button>
              ))}
            </div>
          </div>
        </div>
        {err && <p className="mt-2 text-theme-sm text-error-500">{err}</p>}
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button size="sm" onClick={start} disabled={!coins.length || !tfs.length || !!dl?.running}>
            DOWNLOAD CANDLES
          </Button>
          {dl?.running && (
            <Button size="sm" variant="outline" onClick={() => api.jobStop("download").then(poll)}>STOP</Button>
          )}
          {/* FIRST, because it is the one button that clears every kind. */}
          <Button size="sm" onClick={resolve}
            disabled={!pending?.count || !!dl?.running}>
            {pending?.count
              ? `RESOLVE ${pending.count.toLocaleString()} PENDING`
              : pending?.indexing ? "RESOLVE PENDING · indexing"
              : "RESOLVE PENDING · nothing pending"}
          </Button>
          <Button size="sm" variant="outline" onClick={update} disabled={!gaps?.pairs || !!dl?.running}>
            UPDATE CANDLES
          </Button>
          <Button size="sm" variant="outline" onClick={retry} disabled={!lost?.count || !!dl?.running}>
            {lost?.count ? `RETRY ${lost.count} FAILED` : "RETRY FAILED · nothing lost"}
          </Button>
          {dl?.running && <Badge size="sm" color="info">{
            dl.mode === "update" ? "updating"
            : dl.mode === "retry" ? "retrying"
            /* RESOLVE had no case, so it wore the "downloading" label for a
               whole run (2026-09-05) — every mode the job can be in needs one. */
            : dl.mode === "resolve" ? "resolving pending"
            : "downloading"}</Badge>}
          {/* WHY the buttons are grey. A top-up now starts BY ITSELF when the
              store goes 3h stale (candle_autopilot), so from 2026-09-06 these
              can be disabled at a moment the operator did not cause — and a
              button that greys out for no stated reason reads as broken. */}
          {dl?.running
            ? <span className="text-theme-xs text-gray-500 dark:text-gray-400">
                the buttons wait while a {dl.mode === "update" ? "top-up"
                  : dl.mode === "resolve" ? "resolve" : "download"} is running
                — candles top up on their own once the store is 3h behind
              </span>
            : !coins.length && <span className="text-theme-xs text-gray-500 dark:text-gray-400">DOWNLOAD needs a coin; UPDATE tops up everything already stored</span>}
        </div>
        {!!lost?.count && (
          <p className="mt-3 text-theme-xs text-error-500">
            lost by the last download{lost.written ? ` (${lost.written})` : ""}:{" "}
            {lost.pairs.map((p) => `${p.symbol.replace("_USDT", "")} ${p.timeframe}`).join(" · ")}
            {" "}— RETRY fetches exactly these
          </p>
        )}
        {/* A contract MEXC dropped can never be fetched: it is NOT lost, and a
            RETRY button offering it is a button that cannot succeed. MEZO and
            DRV failed four times at 2:43pm on 2026-08-27 and would have failed
            on every retry after it — the operator's "this update candles is not
            reliable". Named here, skipped by every run. */}
        {!!lost?.delisted_count && (
          <p className="mt-3 text-theme-xs text-warning-600 dark:text-warning-400">
            {lost.delisted_count} pair(s) DELISTED on MEXC, skipped by every
            download and never retried:{" "}
            {(lost.delisted ?? []).map((p) =>
              `${p.symbol.replace("_USDT", "")} ${p.timeframe}`).join(" · ")}
            {" "}— nothing can fetch a contract the venue dropped
          </p>
        )}
        {lost && !lost.count && !!lost.recovered?.length && (
          <p className="mt-3 text-theme-xs text-gray-500 dark:text-gray-400">
            nothing to retry — the pairs lost by the failed run at {lost.failed_run_when} are back in the store:{" "}
            {lost.recovered.map((p) =>
              `${p.symbol.replace("_USDT", "")} ${p.timeframe} (${(p.bars ?? 0).toLocaleString()} bars, stored ${p.when})`).join(" · ")}
            {lost.unnamed
              ? ` · ${lost.unnamed} more error${lost.unnamed === 1 ? "" : "s"} from that run ${lost.unnamed === 1 ? "was" : "were"} not named`
              : ""}
          </p>
        )}
        {/* "is the candles complete now?" — counted against every contract MEXC
            lists x five timeframes, with the missing pairs named */}
        {whole && (
          <p className={`mt-3 text-theme-xs font-medium ${
            whole.complete ? "text-success-600 dark:text-success-400"
              : whole.ok ? "text-error-500" : "text-gray-500 dark:text-gray-400"}`}>
            {!whole.ok
              ? `store completeness unknown — ${whole.why}`
              : whole.complete
                ? `store complete: ${(whole.stored ?? 0).toLocaleString()} of ${(whole.wanted ?? 0).toLocaleString()} pairs (${whole.contracts} contracts × 5 timeframes)`
                : `store missing ${whole.missing.length.toLocaleString()} of ${(whole.wanted ?? 0).toLocaleString()} pairs: ${
                    whole.missing.slice(0, 8).map((m) => `${m.symbol.replace("_USDT", "")} ${m.timeframe}`).join(" · ")}${
                    whole.missing.length > 8 ? ` · and ${whole.missing.length - 8} more` : ""}`}
          </p>
        )}
        {gaps && (
          <p className="mt-3 text-theme-xs text-gray-500 dark:text-gray-400">
            {gaps.pairs.toLocaleString()} pair(s) stored ·{" "}
            {gaps.behind
              ? <><b>{gaps.behind}</b> behind by more than a bar
                  {gaps.worst && <> · furthest is {gaps.worst.symbol.replace("_USDT", "")} {gaps.worst.timeframe}, {gaps.worst.hours_behind}h</>}
                  {" "}— UPDATE CANDLES fills exactly those gaps</>
              : "all up to date"}
            {/* the ones no run can ever catch up: out of the count above, so
                "N behind" can actually reach zero (review, 2026-08-27) */}
            {gaps.delisted_count
              ? <span className="text-warning-600 dark:text-warning-400">
                  {" · "}{gaps.delisted_count} more stored but DELISTED on MEXC
                  {gaps.delisted?.[0] && <> ({gaps.delisted[0].symbol.replace("_USDT", "")} {gaps.delisted[0].timeframe}
                    {gaps.delisted.length > 1 ? ` and ${gaps.delisted.length - 1} more` : ""})</>}
                  {" "}— nothing can fetch them; they are not counted above
                </span>
              : null}
          </p>
        )}
        <JobProgress s={dl} />
        {/* did it work? the progress file only holds the LAST run, so the
            outcome of every run comes from the event store. Keyed on
            `running` so a finishing job refreshes the list. */}
        <DownloadHistory refreshKey={dl?.running ? 1 : 0} />
      </div>
      <StoragePanel />
    </div>
  );
}
