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
import StoragePanel from "@/components/backtest/StoragePanel";

const TFS = ["15m", "30m", "1h", "4h", "1d"];

function Progress({ s }: { s: JobStatus | null }) {
  if (!s || (!s.running && !s.finished)) return null;
  const pct = s.total ? Math.min(100, (100 * (s.done ?? 0)) / s.total) : 0;
  return (
    <div className="mt-3">
      <div className="mb-1 flex items-center justify-between text-theme-xs text-gray-500 dark:text-gray-400">
        <span>{s.running ? (s.now ?? "running…") : s.error ? `failed: ${s.error}` : (s.note || "finished")}</span>
        <span>
          {s.done ?? 0}/{s.total ?? 0}
          {s.bars_stored != null && ` · ${s.bars_stored.toLocaleString()} bars stored`}
          {s.errors != null && s.errors > 0 && ` · ${s.errors} error(s)`}
        </span>
      </div>
      <div className="h-2 w-full rounded-full bg-gray-200 dark:bg-gray-800">
        <div className={`h-2 rounded-full ${s.error ? "bg-error-500" : s.running ? "bg-brand-500" : "bg-success-500"}`}
          style={{ width: `${s.running ? Math.max(pct, 3) : 100}%` }} />
      </div>
    </div>
  );
}

export default function DownloadScreen() {
  const [coins, setCoins] = useState<string[]>([]);
  const [tfs, setTfs] = useState<string[]>(["15m", "30m", "1h", "4h"]);
  const [dl, setDl] = useState<JobStatus | null>(null);
  const [err, setErr] = useState("");
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const poll = useCallback(() => {
    api.jobStatus("download").then(setDl).catch(() => {});
  }, []);
  useEffect(() => {
    poll();
    timer.current = setInterval(poll, 4000);
    return () => { if (timer.current) clearInterval(timer.current); };
  }, [poll]);

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
          {dl?.running && <Badge size="sm" color="info">running</Badge>}
          {!coins.length && <span className="text-theme-xs text-gray-500 dark:text-gray-400">pick at least one coin — nothing downloads on its own</span>}
        </div>
        <Progress s={dl} />
      </div>
      <StoragePanel />
    </div>
  );
}
