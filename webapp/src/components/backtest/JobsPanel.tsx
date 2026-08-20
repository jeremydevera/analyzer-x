"use client";
/**
 * Download candles and run backtests — the detached jobs, driven over HTTP.
 * Progress polls every 4s and survives reloads because the truth lives in
 * the job's progress file on disk, not in this component.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { api, API_BASE, JobStatus } from "@/lib/api";
import Button from "@/components/ui/button/Button";
import Badge from "@/components/ui/badge/Badge";

const TFS = ["15m", "30m", "1h", "4h", "1d"];
const WINDOWS: Record<string, number> = {
  "Previous month": 30, "Previous 3 months": 90,
  "Previous 6 months": 180, "Previous 1 year": 365,
};
const inputCls =
  "h-10 w-full rounded-lg border border-gray-300 bg-transparent px-3 " +
  "text-theme-sm text-gray-700 focus:outline-hidden focus:ring-2 " +
  "focus:ring-brand-500/20 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-300";

function Progress({ s }: { s: JobStatus | null }) {
  if (!s || (!s.running && !s.finished)) return null;
  const pct = s.total ? Math.min(100, (100 * (s.done ?? 0)) / s.total) : 0;
  return (
    <div className="mt-3">
      <div className="mb-1 flex items-center justify-between text-theme-xs text-gray-500 dark:text-gray-400">
        <span>
          {s.running ? (s.now ?? "running…") : s.error ? `failed: ${s.error}` : (s.note || "finished")}
        </span>
        <span>
          {s.done ?? 0}/{s.total ?? 0}
          {s.bars_stored != null && ` · ${s.bars_stored.toLocaleString()} bars`}
          {s.rows != null && ` · ${s.rows.toLocaleString()} rows`}
        </span>
      </div>
      <div className="h-2 w-full rounded-full bg-gray-200 dark:bg-gray-800">
        <div
          className={`h-2 rounded-full ${s.error ? "bg-error-500" : s.running ? "bg-brand-500" : "bg-success-500"}`}
          style={{ width: `${s.running ? Math.max(pct, 3) : 100}%` }}
        />
      </div>
      {!s.running && s.report && (
        <a
          className="mt-2 inline-block text-theme-sm font-medium text-brand-600 underline dark:text-brand-400"
          href={`http://localhost:8503/app/static/bt/${s.report}`}
          target="_blank"
          rel="noopener"
        >
          OPEN THE REPORT ↗
        </a>
      )}
    </div>
  );
}

export default function JobsPanel() {
  const [coinsText, setCoinsText] = useState("PI_USDT");
  const [tfs, setTfs] = useState<string[]>(["15m", "30m", "1h", "4h"]);
  const [win, setWin] = useState("Previous 1 year");
  const [dl, setDl] = useState<JobStatus | null>(null);
  const [bt, setBt] = useState<JobStatus | null>(null);
  const [err, setErr] = useState("");
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const poll = useCallback(() => {
    api.jobStatus("download").then(setDl).catch(() => {});
    api.jobStatus("backtest").then(setBt).catch(() => {});
  }, []);

  useEffect(() => {
    poll();
    timer.current = setInterval(poll, 4000);
    return () => { if (timer.current) clearInterval(timer.current); };
  }, [poll]);

  const coins = coinsText.split(/[\s,]+/).map((c) => c.trim().toUpperCase())
    .filter(Boolean).map((c) => (c.endsWith("_USDT") ? c : `${c}_USDT`));

  const start = async (kind: "download" | "backtest") => {
    setErr("");
    try {
      if (kind === "download") await api.jobStart("download", { coins, tfs });
      else
        await api.jobStart("backtest", {
          coins, tfs, days: WINDOWS[win], base: 5.0,
          label: "react", deployed: [],
        });
      poll();
    } catch (e) {
      setErr(String(e));
    }
  };

  return (
    <div className="overflow-hidden rounded-2xl border border-gray-200 bg-white p-5 dark:border-white/[0.05] dark:bg-white/[0.03]">
      <h3 className="text-base font-semibold text-gray-800 dark:text-white/90">
        Market data & backtests
      </h3>
      <p className="mb-4 text-theme-xs text-gray-500 dark:text-gray-400">
        Jobs run detached on this Mac — switching tabs or closing the browser
        does not stop them. API: {API_BASE}
      </p>
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="sm:col-span-1">
          <label className="mb-1 block text-theme-xs text-gray-500 dark:text-gray-400">Coins (comma or space separated)</label>
          <input className={inputCls} value={coinsText} onChange={(e) => setCoinsText(e.target.value)} />
        </div>
        <div>
          <label className="mb-1 block text-theme-xs text-gray-500 dark:text-gray-400">Timeframes</label>
          <div className="flex flex-wrap gap-2 pt-1.5">
            {TFS.map((t) => (
              <button
                key={t}
                onClick={() => setTfs((cur) => cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t])}
                className={`rounded-full px-3 py-1 text-theme-xs font-medium ${tfs.includes(t)
                  ? "bg-brand-500 text-white"
                  : "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300"}`}
              >
                {t}
              </button>
            ))}
          </div>
        </div>
        <div>
          <label className="mb-1 block text-theme-xs text-gray-500 dark:text-gray-400">Window</label>
          <select className={inputCls} value={win} onChange={(e) => setWin(e.target.value)}>
            {Object.keys(WINDOWS).map((w) => <option key={w}>{w}</option>)}
          </select>
        </div>
      </div>
      {err && <p className="mt-2 text-theme-sm text-error-500">{err}</p>}

      <div className="mt-4 grid gap-6 lg:grid-cols-2">
        <div>
          <div className="flex items-center gap-3">
            <Button size="sm" onClick={() => start("download")}
              disabled={!coins.length || !tfs.length || !!dl?.running}>
              DOWNLOAD CANDLES
            </Button>
            {dl?.running && (
              <Button size="sm" variant="outline" onClick={() => api.jobStop("download").then(poll)}>
                STOP
              </Button>
            )}
            {dl?.running && <Badge size="sm" color="info">running</Badge>}
          </div>
          <Progress s={dl} />
        </div>
        <div>
          <div className="flex items-center gap-3">
            <Button size="sm" onClick={() => start("backtest")}
              disabled={!coins.length || !tfs.length || !!bt?.running}>
              BACKTEST
            </Button>
            {bt?.running && (
              <Button size="sm" variant="outline" onClick={() => api.jobStop("backtest").then(poll)}>
                STOP
              </Button>
            )}
            {bt?.running && <Badge size="sm" color="info">running</Badge>}
          </div>
          <Progress s={bt} />
        </div>
      </div>
    </div>
  );
}
