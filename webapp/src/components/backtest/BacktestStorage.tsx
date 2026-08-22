"use client";
/** What the measured grid costs on this Mac, and how current each pair is.
 *
 * Two freshness figures on purpose. `measured through` is the last CANDLE the
 * grid was tested against; `last run` is when the file was written. A pair
 * re-run an hour ago can still be measured through yesterday, and showing only
 * one of the two hides that.
 */
import { useCallback, useEffect, useState } from "react";
import { BtStorage, backtestApi, fmtBytes } from "@/lib/api";
import { Table, TableBody, TableCell, TableHeader, TableRow } from "@/components/ui/table";

const HEADS = ["coin", "tf", "rows", "combos", "size", "measured through", "last run"];

export default function BacktestStorage() {
  const [d, setD] = useState<BtStorage | null>(null);
  const load = useCallback(() => {
    backtestApi.storage().then(setD).catch(() => {});
  }, []);
  useEffect(() => { load(); const t = setInterval(load, 30_000); return () => clearInterval(t); }, [load]);

  if (!d) return null;
  return (
    <div className="min-w-0 overflow-hidden rounded-2xl border border-gray-200 bg-white dark:border-white/[0.05] dark:bg-white/[0.03]">
      <div className="px-5 pt-4">
        <h3 className="text-base font-semibold text-gray-800 dark:text-white/90">
          Backtest store
        </h3>
        <p className="text-theme-xs text-gray-500 dark:text-gray-400">
          {d.total_rows.toLocaleString()} measured rows over {d.pairs} pair
          {d.pairs === 1 ? "" : "s"} · {d.coins} coin{d.coins === 1 ? "" : "s"} ·{" "}
          {fmtBytes(d.total_bytes)} on this Mac
          {d.newest_measured ? ` · newest bar tested ${d.newest_measured}` : ""}
        </p>
        {d.incomplete > 0 && (
          // a pair with rows and no watermark was interrupted: its work was
          // kept by a checkpoint but it never finished
          <p className="mt-1 text-theme-xs font-medium text-warning-600 dark:text-warning-400">
            {d.incomplete} pair{d.incomplete === 1 ? "" : "s"} interrupted part-way —
            the finished combinations are kept; re-run to complete them
          </p>
        )}
      </div>
      <div className="mt-3 w-full overflow-x-auto">
        <Table>
          <TableHeader className="border-y border-gray-100 dark:border-white/[0.05]">
            <TableRow>
              {HEADS.map((h) => (
                <TableCell key={h} isHeader className="px-4 py-2 text-theme-xs font-medium text-gray-500 text-start dark:text-gray-400">{h}</TableCell>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
            {d.rows.map((r) => (
              <TableRow key={`${r.coin}-${r.tf}`}>
                <TableCell className="px-4 py-2 text-theme-xs font-medium text-gray-800 dark:text-white/90">{r.coin}</TableCell>
                <TableCell className="px-4 py-2 text-theme-xs text-gray-500 dark:text-gray-400">{r.tf}</TableCell>
                <TableCell className="px-4 py-2 font-mono text-theme-xs tabular-nums text-gray-700 dark:text-gray-300">{r.rows.toLocaleString()}</TableCell>
                <TableCell className="px-4 py-2 font-mono text-theme-xs tabular-nums text-gray-500 dark:text-gray-400">{/* null = not indexed yet. Printing 0 claimed a measured pair had no
                    combinations at all. */}
                  {r.combos == null ? <span className="text-gray-400">not indexed yet</span>
                    : r.combos.toLocaleString()}</TableCell>
                <TableCell className="px-4 py-2 font-mono text-theme-xs tabular-nums text-gray-700 dark:text-gray-300">{fmtBytes(r.bytes)}</TableCell>
                <TableCell className="px-4 py-2 text-theme-xs text-gray-500 dark:text-gray-400">
                  {r.incomplete
                    ? <span className="font-medium text-warning-600 dark:text-warning-400">interrupted</span>
                    : (r.measured_through ?? "—")}
                </TableCell>
                <TableCell className="px-4 py-2 text-theme-xs text-gray-400 dark:text-gray-500">{r.last_run ?? "—"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
