"use client";
/** LOGS — what is still pending on this machine, and every named error.
 *
 * Operator, 2026-09-03: *"if there is error create a seperate section called
 * logs just like in candles module si i can see what is pending on my side and
 * what are errors"* — and 2026-09-05: *"i want you to create 2 seperate
 * -folder-like tabs — pending and errors, errors should go to errors tab
 * while pending should go to pending tab"*, so GitHub Actions failures have a
 * place of their own instead of sharing one scroll with the pending list.
 *
 * PENDING is counted from the store as it is NOW (candle files against state
 * files), not from any run's memory. ERRORS are NAMED, never counted: a bare
 * "3 failed" sends the reader back to a log to find out which three, which is
 * the mistake the download job already paid for. The GitHub shard errors ride
 * in the same list (`where: "GitHub shard N"`), so the ERRORS tab is where a
 * cloud run's failures land.
 *
 * Each tab's LABEL carries its own count, derived from the same payload as
 * the tab's content (label-must-match-data) — and the panel OPENS on the
 * ERRORS tab when there is an error to see, because that is what the operator
 * asked the tabs for.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { api, BacktestLogs } from "@/lib/api";

const TF_ORDER = ["15m", "30m", "1h", "4h", "1d"];

export default function LogsPanel({ refreshKey = 0 }: { refreshKey?: number }) {
  const [d, setD] = useState<BacktestLogs | null>(null);
  const [err, setErr] = useState("");
  const [openPending, setOpenPending] = useState(false);
  const [resolving, setResolving] = useState(false);
  const [resolved, setResolved] = useState("");
  // which folder is open. Picked ONCE from the first payload — errors first
  // when any exist, pending otherwise — then it is the operator's own click,
  // never yanked by a 30s refresh.
  const [tab, setTab] = useState<"pending" | "errors" | null>(null);
  const picked = useRef(false);

  const load = useCallback(() => {
    api.backtestLogs()
      .then((r) => {
        setD(r); setErr("");
        if (!picked.current) {
          picked.current = true;
          setTab(r.error_count ? "errors" : "pending");
        }
      })
      .catch((e) => setErr(String(e?.message ?? e)));
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 30_000);
    return () => clearInterval(t);
  }, [load, refreshKey]);

  /** RESOLVE PENDING — one dispatch for every never-measured pair.
   *
   * Operator, Sep 05, 2026: "when i click this i want you to resolve all
   * pending". What comes back is what was SENT (the count and the frames), so
   * the line below reports the dispatch instead of claiming one. */
  const resolvePending = async () => {
    setResolving(true); setResolved("");
    try {
      const r = await api.backtestResolvePending();
      setResolved(r.why);
      load();
    } catch (e) {
      setResolved(String((e as Error)?.message ?? e));
    } finally {
      setResolving(false);
    }
  };

  if (err) {
    return (
      <div className="mt-5 overflow-hidden rounded-2xl border border-gray-200 bg-white p-5 dark:border-white/[0.05] dark:bg-white/[0.03]">
        <h3 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">LOGS</h3>
        <p className="mt-2 text-theme-xs text-error-500">could not read the logs — {err}</p>
      </div>
    );
  }
  if (!d || !tab) {
    return (
      <div className="mt-5 overflow-hidden rounded-2xl border border-gray-200 bg-white p-5 dark:border-white/[0.05] dark:bg-white/[0.03]">
        <h3 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">LOGS</h3>
        <p className="mt-2 text-theme-xs text-gray-500 dark:text-gray-400">reading…</p>
      </div>
    );
  }

  const p = d.pending;
  const tfs = TF_ORDER.filter((t) => p.by_timeframe[t]);
  // THE BUTTON PROMISES WHAT A SWEEP CAN DO. 653 pending on Sep 06, 2026 was
  // 8 measurable and 645 under their timeframe's bar floor — a button offering
  // to resolve 653 would send twenty runners for an hour, move the count by 8
  // and read as broken (label-must-match-data).
  const can = p.measurable ?? p.count;
  const short = p.too_short ?? 0;
  const shortTfs = TF_ORDER.filter((t) => (p.too_short_by_timeframe ?? {})[t]);
  // the cloud half of "0 errors": a shard that never reported cannot be read
  // for failures, so a green count has to say how many were silent
  const cloudBlind = !d.cloud.ok || !!d.cloud.silent;

  // the folder tabs. Counts on the LABELS come from the same payload the
  // tab bodies render, so a tab can never promise what its page lacks.
  const folder = (k: "pending" | "errors", label: string, n: number,
                  hot: boolean) => (
    <button
      key={k} role="tab" aria-selected={tab === k}
      onClick={() => setTab(k)}
      className={`relative -mb-px rounded-t-lg border border-b-0 px-4 py-2 text-theme-xs font-semibold ${
        tab === k
          ? "border-gray-200 bg-white text-gray-800 dark:border-white/[0.08] dark:bg-white/[0.06] dark:text-white/90"
          : "border-transparent bg-gray-50 text-gray-500 hover:text-gray-700 dark:bg-white/[0.02] dark:text-gray-400 dark:hover:text-gray-200"}`}>
      {label}
      <span className={`ml-2 rounded-full px-1.5 py-0.5 text-[10px] font-bold ${
        n === 0
          ? "bg-success-50 text-success-600 dark:bg-success-500/15 dark:text-success-400"
          : hot
            ? "bg-error-50 text-error-600 dark:bg-error-500/15 dark:text-error-400"
            : "bg-warning-50 text-warning-600 dark:bg-warning-500/15 dark:text-warning-400"}`}>
        {n.toLocaleString()}
      </span>
    </button>
  );

  return (
    <div className="mt-5 overflow-hidden rounded-2xl border border-gray-200 bg-white p-5 dark:border-white/[0.05] dark:bg-white/[0.03]">
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">LOGS</h3>
        <span className="ml-auto text-theme-xs text-gray-500 dark:text-gray-400">
          checked {d.checked}
        </span>
      </div>

      {/* --------------------------------------------- where the last run went */}
      {!!d.plan?.why && (
        <p className="mt-2 text-theme-xs text-gray-500 dark:text-gray-400">
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

      {/* ---------------------------------------------------- the folder tabs */}
      <div role="tablist" aria-label="Logs"
           className="mt-3 flex items-end gap-1 border-b border-gray-200 dark:border-white/[0.08]">
        {folder("pending", "PENDING", p.count, false)}
        {folder("errors", "ERRORS", d.error_count, true)}
      </div>

      {tab === "pending" && (
        <div role="tabpanel" aria-label="Pending">
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
            {!!p.delisted && (
              <>
                {" · "}
                <span title="MEXC no longer lists these contracts, so no run anywhere can measure them. Their candles stay stored; they are simply not counted as pending.">
                  {p.delisted} pair(s) on delisted contracts left out
                  ({(p.delisted_coins ?? []).join(", ")})
                </span>
              </>
            )}
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
          {/* RESOLVE PENDING lives in the tab whose number it moves. Its LABEL
              carries the count from the same `pending` payload as the tab's
              badge, never a second source (label-must-match-data). */}
          <div className="mt-3">
            <button
              onClick={resolvePending}
              disabled={resolving || !can}
              title={can
                ? `Measure the ${can.toLocaleString()} pending pair(s) a sweep can actually do. Dispatches GitHub Actions for the timeframes they are in; pairs already measured here are not overwritten.${short ? ` The other ${short.toLocaleString()} are under their timeframe's bar floor — too young for any sweep to make a row from.` : ""}`
                : p.count
                  ? `None of the ${p.count.toLocaleString()} pending pair(s) can be measured — ${short.toLocaleString()} are under their timeframe's bar floor`
                  : "Every pair with candles on this PC has been measured"}
              className={`rounded-lg px-3 py-1 text-theme-xs font-medium ${
                can && !resolving
                  ? "bg-warning-500 text-white hover:bg-warning-600"
                  : "cursor-default bg-gray-100 text-gray-400 dark:bg-white/[0.06] dark:text-gray-500"}`}>
              {resolving
                ? "RESOLVE PENDING · dispatching…"
                : can
                  ? `RESOLVE PENDING · ${can.toLocaleString()}`
                  : p.count
                    ? "RESOLVE PENDING · none measurable"
                    : "RESOLVE PENDING · nothing pending"}
            </button>
            {/* WHY the number will not reach zero. Without this the operator
                sees a disabled button beside a badge saying 653 and has no way
                to learn that 645 of them are young contracts. */}
            {!!short && (
              <p className="mt-2 text-theme-xs text-gray-500 dark:text-gray-400">
                <b className="text-warning-600 dark:text-warning-400">
                  {short.toLocaleString()}
                </b>{" "}
                of the {p.count.toLocaleString()} are under their timeframe&apos;s
                bar floor{shortTfs.length
                  ? ` (${shortTfs.map((t) => `${t}: ${(p.too_short_by_timeframe ?? {})[t]}`).join(" · ")})`
                  : ""} — young contracts, and no sweep makes a row from a
                history that short. They stay pending until they have more candles.
              </p>
            )}
            {resolved && (
              <p className="mt-2 text-theme-xs text-brand-600 dark:text-brand-400">
                {resolved}
              </p>
            )}
          </div>
        </div>
      )}

      {tab === "errors" && (
        <div role="tabpanel" aria-label="Errors">
          {d.errors.length ? (
            <div className="mt-3 max-h-72 overflow-y-auto rounded-lg border border-gray-100 dark:border-white/[0.05]">
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
          {/* the GitHub side of a green tab: a silent shard is unread, not
              clean — say so INSIDE the errors folder, where the reader is */}
          {d.errors.length > 0 && cloudBlind && (
            <p className="mt-2 text-theme-xs text-gray-500 dark:text-gray-400">
              {d.cloud.ok
                ? `${d.cloud.silent} GitHub shard(s) have not reported yet — their failures cannot be read`
                : `GitHub could not be read (${d.cloud.why}) — its failures are unknown`}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
