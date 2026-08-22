"use client";
/**
 * Storage on THIS machine, per coin.
 *
 * A tab per timeframe plus ALL: on ALL, a row is the coin's whole store and
 * the timeframes it holds; on a timeframe tab, every figure is that timeframe
 * alone — so the sizes on screen always belong to the tab that is open.
 *
 * "last updated" is the newest STORED BAR, not a file mtime: a rewrite that
 * added no bars is not an update.
 */
import { useEffect, useMemo, useState } from "react";
import { api, CoinStorageRow, CoverageRow, fmtMB, fmtWhenMs } from "@/lib/api";
import {
  Table, TableBody, TableCell, TableHeader, TableRow,
} from "@/components/ui/table";

const PER_PAGE = 15;
const TF_ORDER = ["15m", "30m", "1h", "4h", "1d"];

const ago = (ms: number | null) => {
  if (!ms) return "—";
  const mins = Math.max(0, Math.round((Date.now() - ms) / 60000));
  if (mins < 60) return `${mins}m ago`;
  const h = Math.floor(mins / 60);
  if (h < 48) return `${h}h ${mins % 60}m ago`;
  return `${Math.floor(h / 24)}d ${h % 24}h ago`;
};

// one shared formatter, or this drifts: this rendered "Aug 22, 12:00 PM" —
// no year, and a space before the AM/PM
const stamp = (ms: number | null) => (ms ? fmtWhenMs(ms) : "—");

interface Grouped {
  coin: string;
  tf_names: string[];
  candles: number;
  rows: number;
  states: number;
  total: number;
  last_ms: number | null;
  bars: number;
}

export default function StoragePanel() {
  const [rows, setRows] = useState<CoinStorageRow[]>([]);
  const [coverage, setCoverage] = useState<CoverageRow[]>([]);
  const [err, setErr] = useState("");
  const [pick, setPick] = useState("");
  const [tab, setTab] = useState("ALL");
  const [page, setPage] = useState(1);

  useEffect(() => {
    api.storageByCoin().then((d) => setRows(d.rows)).catch((e) => setErr(String(e)));
    api.coverage().then((d) => setCoverage(d.rows)).catch(() => {});
  }, []);

  useEffect(() => { setPage(1); setPick(""); }, [tab]);

  const tabs = useMemo(() => {
    const present = [...new Set(rows.map((r) => r.tf))]
      .sort((a, b) => TF_ORDER.indexOf(a) - TF_ORDER.indexOf(b));
    return ["ALL", ...present];
  }, [rows]);

  // one row per coin, over the rows the OPEN TAB covers
  const grouped: Grouped[] = useMemo(() => {
    const src = tab === "ALL" ? rows : rows.filter((r) => r.tf === tab);
    const per = new Map<string, Grouped>();
    for (const r of src) {
      const g = per.get(r.coin) ?? {
        coin: r.coin, tf_names: [], candles: 0, rows: 0, states: 0, total: 0,
        last_ms: null, bars: 0,
      };
      g.tf_names.push(r.tf);
      g.candles += r.candles;
      g.rows += r.rows;
      g.states += r.states;
      g.total += r.total;
      g.bars += r.bars ?? 0;
      if (r.last_ms && (!g.last_ms || r.last_ms > g.last_ms)) g.last_ms = r.last_ms;
      per.set(r.coin, g);
    }
    return [...per.values()]
      .map((g) => ({ ...g, tf_names: g.tf_names.sort((a, b) => TF_ORDER.indexOf(a) - TF_ORDER.indexOf(b)) }))
      .sort((a, b) => b.total - a.total);
  }, [rows, tab]);

  const pages = Math.max(1, Math.ceil(grouped.length / PER_PAGE));
  const shown = grouped.slice((page - 1) * PER_PAGE, page * PER_PAGE);
  const sub = rows.filter((r) => r.coin === pick && (tab === "ALL" || r.tf === tab));
  const totalBytes = grouped.reduce((a, g) => a + g.total, 0);
  const oldest = grouped.reduce<number | null>(
    (a, g) => (g.last_ms && (!a || g.last_ms < a) ? g.last_ms : a), null);

  if (err)
    return (
      <div className="rounded-2xl border border-error-300 bg-error-50 p-4 text-sm text-error-600 dark:border-error-500/30 dark:bg-error-500/10">
        Storage unreadable: {err}
      </div>
    );

  return (
    <div className="flex min-w-0 flex-col gap-5">
      <div className="min-w-0 overflow-hidden rounded-2xl border border-gray-200 bg-white dark:border-white/[0.05] dark:bg-white/[0.03]">
        <div className="flex flex-wrap items-baseline justify-between gap-3 px-5 pt-4">
          <h3 className="text-base font-semibold text-gray-800 dark:text-white/90">Size per coin</h3>
          <span className="text-theme-xs text-gray-500 dark:text-gray-400">
            {tab === "ALL" ? "every timeframe combined" : `${tab} only`} ·{" "}
            {grouped.length} coins · page {page} of {pages} ·{" "}
            <span className="font-semibold text-gray-700 dark:text-gray-200">{fmtMB(totalBytes)} total</span>
            {oldest && <> · oldest bar {ago(oldest)}</>}
          </span>
        </div>

        {/* role=tab so these are addressable: the download screen has pills
            with the same labels, and "the first 15m button" was the wrong one */}
        <div role="tablist" aria-label="storage by timeframe" className="flex flex-wrap gap-1 px-5 pt-3">
          {tabs.map((t) => (
            <button key={t} onClick={() => setTab(t)} role="tab"
              aria-selected={t === tab}
              aria-label={t === "ALL" ? "all timeframes combined" : `${t} only`}
              className={`rounded-lg px-3 py-1 text-theme-xs font-medium transition ${t === tab
                ? "bg-brand-500 text-white"
                : "bg-gray-100 text-gray-600 dark:bg-white/[0.06] dark:text-gray-300"}`}>
              {t}
            </button>
          ))}
        </div>

        <div className="w-full p-2">
          <Table fixed>
            <TableHeader className="border-b border-gray-100 dark:border-white/[0.05]">
              <TableRow>
                {([["coin", "14%"],
                   [tab === "ALL" ? "timeframes downloaded" : "timeframe", "20%"],
                   ["bars", "10%"], ["last updated", "18%"],
                   ["candles", "10%"], ["backtest rows", "10%"],
                   ["resume states", "10%"], ["TOTAL", "8%"]] as [string, string][])
                  .map(([h, w]) => (
                  <TableCell key={h} isHeader style={{ width: w }}
                    className="px-3 py-3 text-theme-xs font-medium text-gray-500 text-start dark:text-gray-400">
                    {h}
                  </TableCell>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
              {shown.map((g) => (
                <TableRow key={g.coin}
                  className={`cursor-pointer hover:bg-gray-50 dark:hover:bg-white/[0.03] ${pick === g.coin ? "bg-brand-50 dark:bg-brand-500/10" : ""}`}
                  onClick={() => setPick(pick === g.coin ? "" : g.coin)}>
                  <TableCell className="px-3 py-2.5 text-theme-sm font-medium text-gray-800 dark:text-white/90">{g.coin}</TableCell>
                  <TableCell className="px-3 py-2.5 text-theme-xs text-gray-500 dark:text-gray-400">
                    <span className="flex flex-wrap gap-1">
                      {g.tf_names.map((t) => (
                        <span key={t} className="rounded bg-gray-100 px-1.5 py-0.5 font-medium text-gray-600 dark:bg-white/[0.06] dark:text-gray-300">{t}</span>
                      ))}
                      {!g.tf_names.length && <span>—</span>}
                    </span>
                  </TableCell>
                  <TableCell className="px-3 py-2.5 text-theme-xs text-gray-500 dark:text-gray-400">
                    {g.bars ? g.bars.toLocaleString() : "—"}
                  </TableCell>
                  <TableCell className="px-3 py-2.5 text-theme-xs leading-tight text-gray-500 dark:text-gray-400">
                    <span className="block text-gray-700 dark:text-gray-300">{ago(g.last_ms)}</span>
                    <span className="block text-[10px]">{stamp(g.last_ms)}</span>
                  </TableCell>
                  <TableCell className="px-3 py-2.5 text-theme-xs text-gray-500 dark:text-gray-400">{fmtMB(g.candles)}</TableCell>
                  <TableCell className="px-3 py-2.5 text-theme-xs text-gray-500 dark:text-gray-400">{fmtMB(g.rows)}</TableCell>
                  <TableCell className="px-3 py-2.5 text-theme-xs text-gray-500 dark:text-gray-400">{fmtMB(g.states)}</TableCell>
                  <TableCell className="px-3 py-2.5 text-theme-xs font-semibold text-gray-800 dark:text-white/90">{fmtMB(g.total)}</TableCell>
                </TableRow>
              ))}
              {!shown.length && (
                <TableRow><TableCell className="px-3 py-4 text-theme-sm text-gray-500 dark:text-gray-400">
                  Nothing stored{tab === "ALL" ? "" : ` on ${tab}`} yet.
                </TableCell></TableRow>
              )}
            </TableBody>
          </Table>
        </div>

        {pages > 1 && (
          <div className="flex flex-wrap items-center gap-1 px-5 pb-3">
            <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1}
              className="rounded-lg border border-gray-200 px-2 py-1 text-theme-xs text-gray-600 disabled:opacity-40 dark:border-gray-700 dark:text-gray-300">prev</button>
            {Array.from({ length: Math.min(pages, 9) }, (_, i) => {
              let a = Math.max(1, page - 4);
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
              <span className="font-semibold">{fmtMB(sub.reduce((a, r) => a + r.total, 0))}</span>{" "}
              across {sub.length} timeframe(s)
            </p>
            <div className="w-full">
              <Table fixed>
                <TableBody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
                  {sub.map((r) => (
                    <TableRow key={r.tf}>
                      <TableCell className="px-4 py-2 text-theme-sm text-gray-800 dark:text-white/90">{r.tf}</TableCell>
                      <TableCell className="px-4 py-2 text-theme-xs text-gray-500 dark:text-gray-400">
                        {r.bars ? `${r.bars.toLocaleString()} bars` : "—"}
                      </TableCell>
                      <TableCell className="px-4 py-2 text-theme-xs text-gray-500 dark:text-gray-400">{ago(r.last_ms)}</TableCell>
                      <TableCell className="px-4 py-2 text-theme-xs text-gray-500 dark:text-gray-400">candles {fmtMB(r.candles)}</TableCell>
                      <TableCell className="px-4 py-2 text-theme-xs text-gray-500 dark:text-gray-400">rows {fmtMB(r.rows)}</TableCell>
                      <TableCell className="px-4 py-2 text-theme-xs text-gray-500 dark:text-gray-400">states {fmtMB(r.states)}</TableCell>
                      <TableCell className="px-4 py-2 text-theme-xs font-medium text-gray-800 dark:text-white/90">{fmtMB(r.total)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        )}
      </div>

      <div className="min-w-0 overflow-hidden rounded-2xl border border-gray-200 bg-white dark:border-white/[0.05] dark:bg-white/[0.03]">
        <div className="flex flex-wrap items-baseline justify-between gap-3 px-5 pt-4">
          <h3 className="text-base font-semibold text-gray-800 dark:text-white/90">Candles on this Mac</h3>
          <span className="text-theme-xs text-gray-500 dark:text-gray-400">
            {coverage.reduce((a, c) => a + c.bars, 0).toLocaleString()} bars ·{" "}
            {coverage.length} coin/timeframe pairs
          </span>
        </div>
        <div className="w-full p-2">
          <Table fixed>
            <TableHeader className="border-b border-gray-100 dark:border-white/[0.05]">
              <TableRow>
                {["coin", "timeframe", "bars", "from", "to", "days"].map((h) => (
                  <TableCell key={h} isHeader className="px-4 py-3 text-theme-xs font-medium text-gray-500 text-start dark:text-gray-400">{h}</TableCell>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
              {coverage.slice(0, 40).map((c) => (
                <TableRow key={`${c.symbol}-${c.timeframe}`}>
                  <TableCell className="px-4 py-2 text-theme-sm font-medium text-gray-800 dark:text-white/90">{c.symbol.replace("_USDT", "")}</TableCell>
                  <TableCell className="px-4 py-2 text-theme-xs text-gray-500 dark:text-gray-400">{c.timeframe}</TableCell>
                  <TableCell className="px-4 py-2 text-theme-xs text-gray-500 dark:text-gray-400">{c.bars.toLocaleString()}</TableCell>
                  <TableCell className="px-4 py-2 text-theme-xs text-gray-500 dark:text-gray-400">{c.first}</TableCell>
                  <TableCell className="px-4 py-2 text-theme-xs text-gray-500 dark:text-gray-400">{c.last}</TableCell>
                  <TableCell className="px-4 py-2 text-theme-xs text-gray-500 dark:text-gray-400">{c.days}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </div>
    </div>
  );
}
