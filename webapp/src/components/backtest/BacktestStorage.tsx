"use client";
/** What the measured grid costs on this Mac, and how current each pair is.
 *
 * Two freshness figures on purpose. `measured through` is the last CANDLE the
 * grid was tested against; `last run` is when the file was written. A pair
 * re-run an hour ago can still be measured through yesterday, and showing only
 * one of the two hides that.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { BtStorage, backtestApi, fmtBytes } from "@/lib/api";
import { Table, TableBody, TableCell, TableHeader, TableRow } from "@/components/ui/table";

const HEADS = ["coin", "tf", "rows", "combos", "size", "measured through", "last run"];

const PER_PAGE = 25;

export default function BacktestStorage() {
  const [d, setD] = useState<BtStorage | null>(null);
  // 4,233 pairs in one table is a page nobody scrolls (asked 2026-08-26)
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const load = useCallback(() => {
    backtestApi.storage().then(setD).catch(() => {});
  }, []);
  useEffect(() => { load(); const t = setInterval(load, 30_000); return () => clearInterval(t); }, [load]);

  const shown = useMemo(() => {
    const rows = d?.rows ?? [];
    const needle = q.trim().toUpperCase();
    return needle
      ? rows.filter((r) => r.coin.toUpperCase().includes(needle)
                        || r.tf.toUpperCase().includes(needle))
      : rows;
  }, [d, q]);
  const pages = Math.max(1, Math.ceil(shown.length / PER_PAGE));
  const at = Math.min(page, pages);
  const slice = shown.slice((at - 1) * PER_PAGE, at * PER_PAGE);

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
      <div className="mt-3 flex flex-wrap items-center gap-2 px-5">
        <input value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }}
               placeholder="find a coin…" aria-label="Find a coin"
               className="h-9 w-40 rounded-lg border border-gray-300 bg-transparent px-3 text-theme-xs text-gray-700 focus:outline-hidden focus:ring-2 focus:ring-brand-500/20 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-300" />
        {/* the page, not the store: {d.pairs} pairs is said above */}
        <span className="text-theme-xs text-gray-500 dark:text-gray-400">
          page {at} of {pages} · rows {shown.length ? (at - 1) * PER_PAGE + 1 : 0}–
          {Math.min(at * PER_PAGE, shown.length)} of {shown.length.toLocaleString()}
          {q ? ` matching "${q}"` : " pair(s)"}
        </span>
        <div className="ml-auto flex items-center gap-1">
          <button onClick={() => setPage(1)} disabled={at <= 1}
                  className="h-8 rounded-lg border border-gray-300 px-2 text-theme-xs text-gray-600 disabled:opacity-40 dark:border-gray-700 dark:text-gray-300">first</button>
          <button onClick={() => setPage(at - 1)} disabled={at <= 1}
                  className="h-8 rounded-lg border border-gray-300 px-2 text-theme-xs text-gray-600 disabled:opacity-40 dark:border-gray-700 dark:text-gray-300">prev</button>
          <button onClick={() => setPage(at + 1)} disabled={at >= pages}
                  className="h-8 rounded-lg border border-gray-300 px-2 text-theme-xs text-gray-600 disabled:opacity-40 dark:border-gray-700 dark:text-gray-300">next</button>
          <button onClick={() => setPage(pages)} disabled={at >= pages}
                  className="h-8 rounded-lg border border-gray-300 px-2 text-theme-xs text-gray-600 disabled:opacity-40 dark:border-gray-700 dark:text-gray-300">last</button>
        </div>
      </div>
      <div className="mt-2 w-full overflow-x-auto">
        <Table>
          <TableHeader className="border-y border-gray-100 dark:border-white/[0.05]">
            <TableRow>
              {HEADS.map((h) => (
                <TableCell key={h} isHeader className="px-4 py-2 text-theme-xs font-medium text-gray-500 text-start dark:text-gray-400">{h}</TableCell>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
            {slice.map((r) => (
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
