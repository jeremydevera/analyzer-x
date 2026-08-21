"use client";
/**
 * Storage on THIS machine: per-coin totals with a per-timeframe breakdown.
 * Every number is the API's number — the cell text is derived from the same
 * payload the caption sums, so label and data cannot disagree.
 */
import { useEffect, useState } from "react";
import { api, CoinStorageRow, CoverageRow, fmtMB } from "@/lib/api";
import {
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const PER_PAGE = 15;

interface CoinTotal {
  coin: string;
  tf_names: string[];
  tfs: number;
  candles: number;
  rows: number;
  states: number;
  total: number;
}

export default function StoragePanel() {
  const [rows, setRows] = useState<CoinStorageRow[]>([]);
  const [coverage, setCoverage] = useState<CoverageRow[]>([]);
  const [pick, setPick] = useState<string>("");
  const [page, setPage] = useState(1);
  const [err, setErr] = useState<string>("");

  useEffect(() => {
    api.storageByCoin().then((d) => setRows(d.rows)).catch((e) => setErr(String(e)));
    api.coverage().then((d) => setCoverage(d.rows)).catch(() => {});
  }, []);

  const perCoin = new Map<string, CoinTotal>();
  for (const r of rows) {
    const c = perCoin.get(r.coin) ?? {
      coin: r.coin, tfs: 0, tf_names: [] as string[], candles: 0, rows: 0,
      states: 0, total: 0,
    };
    c.tfs += 1;
    if (r.tf) c.tf_names.push(r.tf);
    c.candles += r.candles;
    c.rows += r.rows;
    c.states += r.states;
    c.total += r.total;
    perCoin.set(r.coin, c);
  }
  const TF_ORDER = ["15m", "30m", "1h", "4h", "1d"];
  const totals = [...perCoin.values()]
    .map((c) => ({ ...c, tf_names: [...c.tf_names].sort((a, b) => TF_ORDER.indexOf(a) - TF_ORDER.indexOf(b)) }))
    .sort((a, b) => b.total - a.total);
  const pages = Math.max(1, Math.ceil(totals.length / PER_PAGE));
  const shown = totals.slice((page - 1) * PER_PAGE, page * PER_PAGE);
  const sub = rows.filter((r) => r.coin === pick);

  if (err)
    return (
      <div className="rounded-2xl border border-error-300 bg-error-50 p-4 text-sm text-error-600 dark:border-error-500/30 dark:bg-error-500/10">
        Storage unreadable: {err}
      </div>
    );

  return (
    <div className="flex flex-col gap-5">
      <div className="overflow-hidden rounded-2xl border border-gray-200 bg-white dark:border-white/[0.05] dark:bg-white/[0.03]">
        <div className="flex items-baseline justify-between px-5 pt-4">
          <h3 className="text-base font-semibold text-gray-800 dark:text-white/90">
            Size per coin
          </h3>
          <span className="text-theme-xs text-gray-500 dark:text-gray-400">
            {totals.length} coins · page {page} of {pages} ·{" "}
            <span className="font-semibold text-gray-700 dark:text-gray-200">
              {fmtMB(totals.reduce((a, c) => a + c.total, 0))} total
            </span>{" "}
            · candles + backtest rows + resume states, this Mac
          </span>
        </div>
        <div className="max-w-full overflow-x-auto p-2">
          <Table>
            <TableHeader className="border-b border-gray-100 dark:border-white/[0.05]">
              <TableRow>
                {["coin", "timeframes downloaded", "candles", "backtest rows", "resume states", "TOTAL"].map((h) => (
                  <TableCell key={h} isHeader className="px-4 py-3 text-theme-xs font-medium text-gray-500 text-start dark:text-gray-400">
                    {h}
                  </TableCell>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
              {shown.map((c) => (
                <TableRow
                  key={c.coin}
                  className={`cursor-pointer hover:bg-gray-50 dark:hover:bg-white/[0.03] ${pick === c.coin ? "bg-brand-50 dark:bg-brand-500/10" : ""}`}
                  onClick={() => setPick(pick === c.coin ? "" : c.coin)}
                >
                  <TableCell className="px-4 py-2.5 text-theme-sm font-medium text-gray-800 dark:text-white/90">{c.coin}</TableCell>
                  <TableCell className="px-4 py-2.5 text-theme-xs text-gray-500 dark:text-gray-400">
                    <span className="flex flex-wrap gap-1">
                      {c.tf_names.map((t) => (
                        <span key={t} className="rounded bg-gray-100 px-1.5 py-0.5 font-medium text-gray-600 dark:bg-white/[0.06] dark:text-gray-300">{t}</span>
                      ))}
                      {!c.tf_names.length && <span>—</span>}
                    </span>
                  </TableCell>
                  <TableCell className="px-4 py-2.5 text-theme-sm text-gray-500 dark:text-gray-400">{fmtMB(c.candles)}</TableCell>
                  <TableCell className="px-4 py-2.5 text-theme-sm text-gray-500 dark:text-gray-400">{fmtMB(c.rows)}</TableCell>
                  <TableCell className="px-4 py-2.5 text-theme-sm text-gray-500 dark:text-gray-400">{fmtMB(c.states)}</TableCell>
                  <TableCell className="px-4 py-2.5 text-theme-sm font-semibold text-gray-800 dark:text-white/90">{fmtMB(c.total)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        {pages > 1 && (
          <div className="flex flex-wrap items-center gap-1 px-5 pb-3">
            <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1}
              className="rounded-lg border border-gray-200 px-2 py-1 text-theme-xs text-gray-600 disabled:opacity-40 dark:border-gray-700 dark:text-gray-300">prev</button>
            {Array.from({ length: Math.min(pages, 9) }, (_, i) => {
              const half = 4;
              let a = Math.max(1, page - half);
              if (a + 8 > pages) a = Math.max(1, pages - 8);
              return a + i;
            }).filter((n) => n <= pages).map((n) => (
              <button key={n} onClick={() => setPage(n)}
                className={`rounded-lg px-2.5 py-1 text-theme-xs ${n === page
                  ? "bg-brand-500 font-semibold text-white"
                  : "border border-gray-200 text-gray-600 dark:border-gray-700 dark:text-gray-300"}`}>{n}</button>
            ))}
            <button onClick={() => setPage((p) => Math.min(pages, p + 1))} disabled={page >= pages}
              className="rounded-lg border border-gray-200 px-2 py-1 text-theme-xs text-gray-600 disabled:opacity-40 dark:border-gray-700 dark:text-gray-300">next</button>
            <span className="ml-2 text-theme-xs text-gray-500 dark:text-gray-400">
              {PER_PAGE} coins per page · sorted by size
            </span>
          </div>
        )}
        {pick && sub.length > 0 && (
          <div className="border-t border-gray-100 px-5 py-4 dark:border-white/[0.05]">
            <p className="mb-2 text-theme-sm font-medium text-gray-700 dark:text-gray-300">
              {pick}, per timeframe — total{" "}
              <span className="font-semibold">
                {fmtMB(sub.reduce((a, r) => a + r.total, 0))}
              </span>{" "}
              across {sub.length} timeframe(s)
            </p>
            <div className="max-w-full overflow-x-auto">
              <Table>
                <TableBody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
                  {sub.map((r) => (
                    <TableRow key={r.tf}>
                      <TableCell className="px-4 py-2 text-theme-sm text-gray-800 dark:text-white/90">{r.tf}</TableCell>
                      <TableCell className="px-4 py-2 text-theme-sm text-gray-500 dark:text-gray-400">candles {fmtMB(r.candles)}</TableCell>
                      <TableCell className="px-4 py-2 text-theme-sm text-gray-500 dark:text-gray-400">rows {fmtMB(r.rows)}</TableCell>
                      <TableCell className="px-4 py-2 text-theme-sm text-gray-500 dark:text-gray-400">states {fmtMB(r.states)}</TableCell>
                      <TableCell className="px-4 py-2 text-theme-sm font-medium text-gray-800 dark:text-white/90">{fmtMB(r.total)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        )}
      </div>

      <div className="overflow-hidden rounded-2xl border border-gray-200 bg-white dark:border-white/[0.05] dark:bg-white/[0.03]">
        <div className="flex items-baseline justify-between px-5 pt-4">
          <h3 className="text-base font-semibold text-gray-800 dark:text-white/90">
            Candles on this Mac
          </h3>
          <span className="text-theme-xs text-gray-500 dark:text-gray-400">
            {coverage.reduce((a, c) => a + c.bars, 0).toLocaleString()} bars ·{" "}
            {coverage.length} coin/timeframe pairs
          </span>
        </div>
        <div className="max-w-full overflow-x-auto p-2">
          <Table>
            <TableHeader className="border-b border-gray-100 dark:border-white/[0.05]">
              <TableRow>
                {["coin", "timeframe", "bars", "from", "to", "days"].map((h) => (
                  <TableCell key={h} isHeader className="px-4 py-3 text-theme-xs font-medium text-gray-500 text-start dark:text-gray-400">
                    {h}
                  </TableCell>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
              {coverage.slice(0, 30).map((c) => (
                <TableRow key={`${c.symbol}-${c.timeframe}`}>
                  <TableCell className="px-4 py-2 text-theme-sm font-medium text-gray-800 dark:text-white/90">{c.symbol.replace("_USDT", "")}</TableCell>
                  <TableCell className="px-4 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{c.timeframe}</TableCell>
                  <TableCell className="px-4 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{c.bars.toLocaleString()}</TableCell>
                  <TableCell className="px-4 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{c.first}</TableCell>
                  <TableCell className="px-4 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{c.last}</TableCell>
                  <TableCell className="px-4 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{c.days}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </div>
    </div>
  );
}
