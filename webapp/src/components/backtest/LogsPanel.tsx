"use client";
/** LOGS — what is still pending on this machine, and every named error.
 *
 * Operator, 2026-09-03: *"if there is error create a seperate section called
 * logs just like in candles module si i can see what is pending on my side and
 * what are errors"*.
 *
 * The backtest screen had nowhere to see either. A run that failed on 860 pairs
 * read as `done: 860, rows: 0` with no note, and the 741 pairs this machine
 * holds candles for but has never measured were invisible — the only way to
 * learn about them was to ask me in chat.
 *
 * PENDING is counted from the store as it is NOW (candle files against state
 * files), not from any run's memory. ERRORS are NAMED, never counted: a bare
 * "3 failed" sends the reader back to a log to find out which three, which is
 * the mistake the download job already paid for.
 */
import { useCallback, useEffect, useState } from "react";
import { api, BacktestLogs } from "@/lib/api";
import Badge from "@/components/ui/badge/Badge";

const TF_ORDER = ["15m", "30m", "1h", "4h", "1d"];

export default function LogsPanel({ refreshKey = 0 }: { refreshKey?: number }) {
  const [d, setD] = useState<BacktestLogs | null>(null);
  const [err, setErr] = useState("");
  const [openPending, setOpenPending] = useState(false);

  const load = useCallback(() => {
    api.backtestLogs()
      .then((r) => { setD(r); setErr(""); })
      .catch((e) => setErr(String(e?.message ?? e)));
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 30_000);
    return () => clearInterval(t);
  }, [load, refreshKey]);

  if (err) {
    return (
      <div className="mt-5 overflow-hidden rounded-2xl border border-gray-200 bg-white p-5 dark:border-white/[0.05] dark:bg-white/[0.03]">
        <h3 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">LOGS</h3>
        <p className="mt-2 text-theme-xs text-error-500">could not read the logs — {err}</p>
      </div>
    );
  }
  if (!d) {
    return (
      <div className="mt-5 overflow-hidden rounded-2xl border border-gray-200 bg-white p-5 dark:border-white/[0.05] dark:bg-white/[0.03]">
        <h3 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">LOGS</h3>
        <p className="mt-2 text-theme-xs text-gray-500 dark:text-gray-400">reading…</p>
      </div>
    );
  }

  const p = d.pending;
  const tfs = TF_ORDER.filter((t) => p.by_timeframe[t]);
  // the cloud half of "0 errors": a shard that never reported cannot be read
  // for failures, so a green count has to say how many were silent
  const cloudBlind = !d.cloud.ok || !!d.cloud.silent;

  return (
    <div className="mt-5 overflow-hidden rounded-2xl border border-gray-200 bg-white p-5 dark:border-white/[0.05] dark:bg-white/[0.03]">
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">LOGS</h3>
        {/* labels DERIVED from the data, never literals */}
        <Badge size="sm" color={p.count ? "warning" : "success"}>
          {p.count ? `${p.count.toLocaleString()} pending` : "nothing pending"}
        </Badge>
        <Badge size="sm" color={d.error_count ? "error" : cloudBlind ? "light" : "success"}>
          {d.error_count
            ? `${d.error_count.toLocaleString()} error${d.error_count === 1 ? "" : "s"}`
            : cloudBlind ? "no error on this PC" : "no errors"}
        </Badge>
        <span className="ml-auto text-theme-xs text-gray-500 dark:text-gray-400">
          checked {d.checked}
        </span>
      </div>

      {/* ------------------------------------------------ pending, on this PC */}
      <p className="mt-3 text-theme-xs text-gray-500 dark:text-gray-400">
        {p.measured.toLocaleString()} of {p.stored.toLocaleString()} stored pair(s)
        measured
        {p.count ? (
          <>
            {" · "}
            <b className="text-warning-600 dark:text-warning-400">
              {p.count.toLocaleString()} never measured
            </b>
            {tfs.length ? ` (${tfs.map((t) => `${t}: ${p.by_timeframe[t]}`).join(" · ")})` : ""}
            {" "}— UPDATE BACKTEST measures exactly these
          </>
        ) : " — every pair with candles has been measured"}
      </p>
      {!!p.pairs.length && (
        <>
          <button
            onClick={() => setOpenPending((v) => !v)}
            className="mt-2 text-theme-xs font-medium text-brand-600 hover:underline dark:text-brand-400">
            {openPending ? "hide" : "name"} the pending pairs
          </button>
          {openPending && (
            <p className="mt-1 break-words text-theme-xs text-gray-500 dark:text-gray-400">
              {p.pairs.map((x) => `${x.symbol.replace("_USDT", "")} ${x.timeframe}`).join(" · ")}
              {p.unnamed ? ` · and ${p.unnamed.toLocaleString()} more` : ""}
            </p>
          )}
        </>
      )}

      {/* --------------------------------------------- where the last run went */}
      {!!d.plan?.why && (
        <p className="mt-3 text-theme-xs text-gray-500 dark:text-gray-400">
          last UPDATE: {d.plan.why}
          {d.plan.cloud_url && (
            <>
              {" · "}
              <a href={d.plan.cloud_url} target="_blank" rel="noreferrer"
                 className="text-brand-600 hover:underline dark:text-brand-400">
                run {d.plan.cloud_run}
              </a>
            </>
          )}
        </p>
      )}

      {/* -------------------------------------------------------------- errors */}
      {d.errors.length ? (
        <div className="mt-4 max-h-72 overflow-y-auto rounded-lg border border-gray-100 dark:border-white/[0.05]">
          <table className="w-full text-theme-xs">
            <thead className="sticky top-0 bg-gray-50 dark:bg-white/[0.03]">
              <tr className="text-left text-gray-500 dark:text-gray-400">
                <th className="px-3 py-2 font-medium">WHERE</th>
                <th className="px-3 py-2 font-medium">PAIR</th>
                <th className="px-3 py-2 font-medium">ERROR</th>
                <th className="px-3 py-2 font-medium">WHEN</th>
              </tr>
            </thead>
            <tbody>
              {d.errors.map((e, i) => (
                <tr key={i} className="border-t border-gray-100 dark:border-white/[0.05]">
                  <td className="whitespace-nowrap px-3 py-1.5 text-gray-500 dark:text-gray-400">{e.where}</td>
                  <td className="whitespace-nowrap px-3 py-1.5 font-medium text-gray-800 dark:text-white/90">
                    {e.pair.replace("_USDT", "")}
                  </td>
                  <td className="px-3 py-1.5 text-error-500">{e.text}</td>
                  <td className="whitespace-nowrap px-3 py-1.5 text-gray-500 dark:text-gray-400">{e.when}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="mt-3 text-theme-xs text-gray-500 dark:text-gray-400">
          no error has been named by this PC
          {d.cloud.ok
            ? d.cloud.silent
              ? ` · ${d.cloud.silent} GitHub shard(s) have not reported yet, so their failures cannot be read`
              : d.cloud.run ? ` or by GitHub run ${d.cloud.run}` : ""
            : ` · GitHub could not be read (${d.cloud.why}), so its failures are unknown`}
        </p>
      )}
      {d.errors.length > 0 && d.error_count > d.errors.length && (
        <p className="mt-2 text-theme-xs text-gray-500 dark:text-gray-400">
          showing {d.errors.length} of {d.error_count.toLocaleString()}
        </p>
      )}
    </div>
  );
}
