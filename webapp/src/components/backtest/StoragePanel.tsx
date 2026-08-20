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

interface CoinTotal {
  coin: string;
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
  const [err, setErr] = useState<string>("");

  useEffect(() => {
    api.storageByCoin().then((d) => setRows(d.rows)).catch((e) => setErr(String(e)));
    api.coverage().then((d) => setCoverage(d.rows)).catch(() => {});
  }, []);

  const perCoin = new Map<string, CoinTotal>();
  for (const r of rows) {
    const c = perCoin.get(r.coin) ?? {
      coin: r.coin, tfs: 0, candles: 0, rows: 0, states: 0, total: 0,
    };
    c.tfs += 1;
    c.candles += r.candles;
    c.rows += r.rows;
    c.states += r.states;
    c.total += r.total;
    perCoin.set(r.coin, c);
  }
  const totals = [...perCoin.values()].sort((a, b) => b.total - a.total);
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
            {totals.length} coins ·{" "}
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
                {["coin", "timeframes", "candles", "backtest rows", "resume states", "TOTAL"].map((h) => (
                  <TableCell key={h} isHeader className="px-4 py-3 text-theme-xs font-medium text-gray-500 text-start dark:text-gray-400">
                    {h}
                  </TableCell>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
              {totals.map((c) => (
                <TableRow
                  key={c.coin}
                  className={`cursor-pointer hover:bg-gray-50 dark:hover:bg-white/[0.03] ${pick === c.coin ? "bg-brand-50 dark:bg-brand-500/10" : ""}`}
                  onClick={() => setPick(pick === c.coin ? "" : c.coin)}
                >
                  <TableCell className="px-4 py-2.5 text-theme-sm font-medium text-gray-800 dark:text-white/90">{c.coin}</TableCell>
                  <TableCell className="px-4 py-2.5 text-theme-sm text-gray-500 dark:text-gray-400">{c.tfs}</TableCell>
                  <TableCell className="px-4 py-2.5 text-theme-sm text-gray-500 dark:text-gray-400">{fmtMB(c.candles)}</TableCell>
                  <TableCell className="px-4 py-2.5 text-theme-sm text-gray-500 dark:text-gray-400">{fmtMB(c.rows)}</TableCell>
                  <TableCell className="px-4 py-2.5 text-theme-sm text-gray-500 dark:text-gray-400">{fmtMB(c.states)}</TableCell>
                  <TableCell className="px-4 py-2.5 text-theme-sm font-semibold text-gray-800 dark:text-white/90">{fmtMB(c.total)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
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
