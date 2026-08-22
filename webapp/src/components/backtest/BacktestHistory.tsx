"use client";
/** Every backtest run and whether it worked.
 *
 * The job's progress file only holds the LAST run, so a failure scrolled away
 * the moment the next one started — which is how a crash that left a 0-byte
 * report went unnoticed. Source is the local event feed.
 *
 * Laid out like Deployment history (operator's ask): a real table in a scroll
 * box, full width of its column, so the two read as the same kind of record.
 */
import { useCallback, useEffect, useState } from "react";
import { BtHistory, backtestApi } from "@/lib/api";
import { Table, TableBody, TableCell, TableHeader, TableRow } from "@/components/ui/table";

export default function BacktestHistory() {
  const [d, setD] = useState<BtHistory | null>(null);
  const load = useCallback(() => {
    backtestApi.history(50).then(setD).catch(() => {});
  }, []);
  useEffect(() => {
    load();
    const t = setInterval(load, 20_000);
    return () => clearInterval(t);
  }, [load]);

  const rows = d?.rows ?? [];
  return (
    <div className="overflow-hidden rounded-2xl border border-gray-200 bg-white dark:border-white/[0.05] dark:bg-white/[0.03]">
      <h3 className="px-5 pt-4 text-base font-semibold text-gray-800 dark:text-white/90">
        Backtest history
      </h3>
      <p className="px-5 text-theme-xs text-gray-500 dark:text-gray-400">
        every run and whether it worked
        {d ? ` — ${d.total} run${d.total === 1 ? "" : "s"}, ${d.ok} ok` : ""}
        {d && d.failed ? <span className="text-error-500">, {d.failed} failed</span> : null}
      </p>
      <div className="max-h-72 max-w-full overflow-auto p-2">
        <Table>
          <TableHeader className="border-b border-gray-100 dark:border-white/[0.05]">
            <TableRow>
              {["when", "outcome", "rows", "detail"].map((h) => (
                <TableCell key={h} isHeader
                  className="px-3 py-2 text-theme-xs font-medium text-gray-500 text-start dark:text-gray-400">
                  {h}
                </TableCell>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
            {rows.map((r) => (
              <TableRow key={r.ts}>
                <TableCell className="whitespace-nowrap px-3 py-2 text-theme-xs text-gray-500 dark:text-gray-400">
                  {r.when}
                </TableCell>
                <TableCell className="px-3 py-2">
                  {/* the outcome as a WORD, not only a colour */}
                  <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase ${
                    r.ok
                      ? "bg-success-50 text-success-700 dark:bg-success-500/15 dark:text-success-400"
                      : "bg-error-50 text-error-700 dark:bg-error-500/15 dark:text-error-400"}`}>
                    {r.ok ? "success" : r.fatal ? "crashed" : "failed"}
                  </span>
                </TableCell>
                <TableCell className="px-3 py-2 font-mono text-theme-xs tabular-nums text-gray-700 dark:text-gray-300">
                  {r.rows != null ? r.rows.toLocaleString() : "—"}
                </TableCell>
                <TableCell className={`px-3 py-2 text-theme-xs ${
                  r.ok ? "text-gray-500 dark:text-gray-400" : "text-error-500"}`}>
                  {r.detail || "—"}
                </TableCell>
              </TableRow>
            ))}
            {d && !rows.length && (
              <TableRow>
                <TableCell className="px-3 py-4 text-theme-sm text-gray-500 dark:text-gray-400">
                  No backtest has run yet.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
