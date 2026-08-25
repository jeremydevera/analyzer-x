"use client";
/**
 * Download candles onto this Mac. Its own screen because the Backtest screen
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
          Fills this Mac&apos;s store — the candles every backtest reads. Runs detached: leaving this
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
          <Button size="sm" variant="outline" onClick={update} disabled={!gaps?.pairs || !!dl?.running}>
            UPDATE CANDLES
          </Button>
          <Button size="sm" variant="outline" onClick={retry} disabled={!lost?.count || !!dl?.running}>
            {lost?.count ? `RETRY ${lost.count} FAILED` : "RETRY FAILED · nothing lost"}
          </Button>
          {dl?.running && <Badge size="sm" color="info">{dl.mode === "update" ? "updating" : dl.mode === "retry" ? "retrying" : "downloading"}</Badge>}
          {!coins.length && <span className="text-theme-xs text-gray-500 dark:text-gray-400">DOWNLOAD needs a coin; UPDATE tops up everything already stored</span>}
        </div>
        {!!lost?.count && (
          <p className="mt-3 text-theme-xs text-error-500">
            lost by the last download{lost.written ? ` (${lost.written})` : ""}:{" "}
            {lost.pairs.map((p) => `${p.symbol.replace("_USDT", "")} ${p.timeframe}`).join(" · ")}
            {" "}— RETRY fetches exactly these
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
