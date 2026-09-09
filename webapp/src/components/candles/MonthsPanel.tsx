"use client";
/**
 * Storage by MONTH, with a delete per row — to free disk.
 *
 * Operator, 2026-09-09: "in candles create a table showing candles for each
 * month for example feb 2025 march 2025 and able to delete it so that i can
 * free up space same as for backtests results".
 *
 * Two tables, two meanings of "month" (storage_months.py owns the rule):
 * candles = bars whose time falls in the month; results = pairs LAST MEASURED
 * in the month. A delete removes that month AND EVERYTHING OLDER — a hole in
 * the middle of a candle series would never be refilled and would corrupt
 * every signal read across it — and the button says so before it asks twice.
 */
import { useCallback, useEffect, useState } from "react";
import { api, MonthJob, MonthRow, StorageMonths, fmtBytes } from "@/lib/api";
import { Table, TableBody, TableCell, TableHeader, TableRow } from "@/components/ui/table";

type Kind = "candles" | "results";

export default function MonthsPanel() {
  const [d, setD] = useState<StorageMonths | null>(null);
  const [err, setErr] = useState("");
  // the row whose delete is waiting for its second click, per store
  const [arm, setArm] = useState<{ kind: Kind; month: string } | null>(null);

  const load = useCallback(() => {
    api.storageMonths().then((x) => { setD(x); setErr(""); })
      .catch((e) => setErr(String(e)));
  }, []);
  useEffect(() => { load(); }, [load]);
  // while a delete runs, follow it; the tables re-read when it ends
  const running = !!(d?.jobs.candles?.running || d?.jobs.results?.running);
  useEffect(() => {
    if (!running) return;
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [running, load]);

  const del = (kind: Kind, month: string) => {
    setErr("");
    api.deleteMonths(kind, month).then(() => { setArm(null); load(); })
      .catch((e) => { setArm(null); setErr(String(e).replace(/^Error: /, "")); });
  };

  if (!d) return null;
  return (
    <div className="flex min-w-0 flex-col gap-5">
      {err && (
        <div role="alert" className="rounded-2xl border border-warning-300 bg-warning-50 px-4 py-3 text-theme-sm text-warning-700 dark:border-warning-500/30 dark:bg-warning-500/10 dark:text-warning-400">
          {err}
        </div>
      )}
      <MonthTable kind="candles" title="Candles by month"
        sub={`${d.candles.total_bars.toLocaleString()} bars in ${d.candles.files.toLocaleString()} files · ${fmtBytes(d.candles.total_bytes)} · split by month from the candle index, so each row is ≈`}
        approx
        warn="stored strategy rows keep their numbers, but a row's trade log can only be rebuilt from the bars that remain"
        countHead="bars" count={(r) => r.bars ?? 0}
        rows={d.candles.rows} job={d.jobs.candles} writer={d.writers.candles}
        arm={arm} setArm={setArm} del={del} />
      <MonthTable kind="results" title="Backtest results by month measured"
        sub={`${d.results.total_rows.toLocaleString()} rows · ${fmtBytes(d.results.total_bytes)} in rows files and resume states · a month is when the pair was LAST measured; rows.db reuses its space at the next fill`}
        warn="those pairs disappear from Stored strategies until they are measured again"
        countHead="rows" count={(r) => r.rows ?? 0}
        rows={d.results.rows} job={d.jobs.results} writer={d.writers.results}
        arm={arm} setArm={setArm} del={del} />
    </div>
  );
}

function MonthTable(p: {
  kind: Kind; title: string; sub: string; countHead: string;
  approx?: boolean; warn: string;
  count: (r: MonthRow) => number; rows: MonthRow[]; job: MonthJob | null;
  writer: string; arm: { kind: Kind; month: string } | null;
  setArm: (a: { kind: Kind; month: string } | null) => void;
  del: (kind: Kind, month: string) => void;
}) {
  const { kind, rows, job } = p;
  // what "this and older" adds up to, per row — the confirm names the real total
  const cum = (i: number) => rows.slice(i).reduce(
    (a, r) => ({ bytes: a.bytes + r.bytes, pairs: a.pairs + r.pairs,
                 n: a.n + p.count(r) }), { bytes: 0, pairs: 0, n: 0 });
  const busy = !!job?.running;
  return (
    <div className="min-w-0 overflow-hidden rounded-2xl border border-gray-200 bg-white dark:border-white/[0.05] dark:bg-white/[0.03]">
      <div className="flex flex-wrap items-baseline justify-between gap-3 px-5 pt-4">
        <h3 className="text-base font-semibold text-gray-800 dark:text-white/90">{p.title}</h3>
        <span className="text-theme-xs text-gray-500 dark:text-gray-400">{p.sub}</span>
      </div>
      {p.writer && (
        <p className="px-5 pt-2 text-theme-xs text-warning-600 dark:text-warning-400">
          a {p.writer} job is writing this store — deleting waits until it finishes
        </p>
      )}
      {job && (
        <p role="status" className={`px-5 pt-2 text-theme-xs ${job.running ? "text-brand-600 dark:text-brand-400" : job.error_count ? "text-warning-600 dark:text-warning-400" : "text-success-600 dark:text-success-400"}`}>
          {job.running
            ? <>deleting {job.label} and older — {job.phase ? `${job.phase} · ` : ""}{job.done.toLocaleString()} of {job.total.toLocaleString()} {kind === "candles" ? "files" : "pairs"} · {job.rows_removed ? `${job.rows_removed.toLocaleString()} rows out of the index · ` : ""}{fmtBytes(job.freed)} freed so far</>
            : <>deleted {job.label} and older — {fmtBytes(job.freed)} freed
                {kind === "candles"
                  ? <> · {job.bars_removed.toLocaleString()} bars removed · {job.files_trimmed.toLocaleString()} files trimmed · {job.files_removed.toLocaleString()} files removed</>
                  : <> · {job.rows_removed.toLocaleString()} rows dropped · {job.files_removed.toLocaleString()} files removed</>}
                {" · "}{job.finished_at}
                {job.error_count ? <> · {job.error_count} error{job.error_count === 1 ? "" : "s"}: {job.errors[0]}</> : null}
              </>}
        </p>
      )}
      <div className="w-full p-2">
        <Table fixed>
          <TableHeader className="border-b border-gray-100 dark:border-white/[0.05]">
            <TableRow>
              {([["month", "18%"], ["pairs", "14%"], [p.countHead, "18%"],
                 ["size", "16%"], ["", "34%"]] as [string, string][]).map(([h, w], i) => (
                <TableCell key={i} isHeader style={{ width: w }}
                  className="px-3 py-3 text-theme-xs font-medium text-gray-500 text-start dark:text-gray-400">
                  {h}
                </TableCell>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
            {rows.map((r, i) => {
              const armed = p.arm?.kind === kind && p.arm.month === r.month;
              const all = cum(i);
              return (
                <TableRow key={r.month}>
                  <TableCell className="px-3 py-2.5 text-theme-sm font-medium text-gray-800 dark:text-white/90">{r.label}</TableCell>
                  <TableCell className="px-3 py-2.5 text-theme-xs text-gray-500 dark:text-gray-400">{r.pairs.toLocaleString()}</TableCell>
                  <TableCell className="px-3 py-2.5 text-theme-xs text-gray-500 dark:text-gray-400">{p.count(r).toLocaleString()}</TableCell>
                  <TableCell className="px-3 py-2.5 text-theme-xs text-gray-500 dark:text-gray-400">{fmtBytes(r.bytes)}</TableCell>
                  <TableCell className="px-3 py-2.5 text-theme-xs">
                    {i === 0 ? (
                      // the newest month is the one everything reads now
                      <span className="text-gray-400 dark:text-gray-500">newest — kept</span>
                    ) : armed ? (
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="text-warning-700 dark:text-warning-400">
                          delete {r.label} and everything older? {p.approx ? "≈ " : ""}{fmtBytes(all.bytes)} across {all.pairs.toLocaleString()} pairs, {all.n.toLocaleString()} {p.countHead} — {p.warn}
                        </span>
                        <button onClick={() => p.del(kind, r.month)} disabled={busy || !!p.writer}
                          aria-label={`yes, delete ${r.label} and older ${kind}`}
                          className="rounded-lg bg-error-500 px-2.5 py-1 font-semibold text-white disabled:opacity-40">
                          yes, delete
                        </button>
                        <button onClick={() => p.setArm(null)}
                          className="rounded-lg border border-gray-200 px-2.5 py-1 text-gray-600 dark:border-gray-700 dark:text-gray-300">
                          cancel
                        </button>
                      </span>
                    ) : (
                      <button onClick={() => p.setArm({ kind, month: r.month })} disabled={busy || !!p.writer}
                        aria-label={`delete ${r.label} and older ${kind}`}
                        className="rounded-lg border border-error-300 px-2.5 py-1 text-error-600 disabled:opacity-40 dark:border-error-500/40 dark:text-error-400">
                        delete this and older
                      </button>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
            {!rows.length && (
              <TableRow><TableCell className="px-3 py-4 text-theme-sm text-gray-500 dark:text-gray-400">
                Nothing stored yet.
              </TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
