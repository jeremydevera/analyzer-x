"use client";
/**
 * Every stored strategy, filtered — and the trades behind any row on click.
 * The trade log is cross-checked in the UI: its footer sums the rows it
 * shows, and a drift beyond 2% against the stored row is SAID, not hidden
 * (the label-must-match-data rule, ported).
 */
import { useCallback, useEffect, useState } from "react";
import { api, fmtMoney, STRATEGY_SORTS, StrategyRow, TradesResult,
  type IndexStatus, type StrategySort } from "@/lib/api";
import Badge from "@/components/ui/badge/Badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const sel =
  "h-10 rounded-lg border border-gray-300 bg-transparent px-3 text-theme-sm " +
  "text-gray-700 focus:outline-hidden focus:ring-2 focus:ring-brand-500/20 " +
  "dark:border-gray-700 dark:bg-gray-900 dark:text-gray-300";

export default function StrategiesPanel() {
  const [facets, setFacets] = useState<{ coins: string[]; tfs: string[]; signals: string[] }>({ coins: [], tfs: [], signals: [] });
  const [coin, setCoin] = useState("");
  const [tf, setTf] = useState("");
  const [signal, setSignal] = useState("");
  const [profitable, setProfitable] = useState(false);
  const [sort, setSort] = useState<StrategySort>("profit");
  const [rows, setRows] = useState<StrategyRow[]>([]);
  const [total, setTotal] = useState(0);
  const [open, setOpen] = useState<StrategyRow | null>(null);
  const [trades, setTrades] = useState<TradesResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [idx, setIdx] = useState<IndexStatus | null>(null);

  useEffect(() => {
    api.facets().then(setFacets).catch((e) => setErr(String(e)));
  }, []);

  const load = useCallback(() => {
    api.strategies({ coin: coin || undefined, tf: tf || undefined, signal: signal || undefined, profitable, sort, limit: 300 })
      .then((d) => { setRows(d.rows); setTotal(d.total); setIdx(d.index ?? null); setErr(""); })
      .catch((e) => setErr(String(e)));
  }, [coin, tf, signal, profitable, sort]);

  useEffect(load, [load]);
  useEffect(() => {
    if (!idx || (!idx.syncing && idx.behind === 0)) return;
    const t = setTimeout(load, 5000);
    return () => clearTimeout(t);
  }, [idx, load]);

  const view = async (r: StrategyRow) => {
    setOpen(r);
    setTrades(null);
    setBusy(true);
    try {
      setTrades(await api.trades(r));
    } catch (e) {
      setTrades({ log: [], why: String(e) });
    } finally {
      setBusy(false);
    }
  };

  const logSum = trades?.log?.reduce((a, t) => a + (t["pnl $"] ?? 0), 0) ?? 0;
  const drift =
    open && trades && trades.log.length
      ? Math.abs((trades.profit ?? logSum) - (open.profit ?? 0)) >
        Math.max(1, Math.abs(open.profit ?? 0) * 0.02)
      : false;

  return (
    <div className="overflow-hidden rounded-2xl border border-gray-200 bg-white dark:border-white/[0.05] dark:bg-white/[0.03]">
      <div className="flex flex-wrap items-end gap-3 px-5 pt-4">
        <div>
          <h3 className="text-base font-semibold text-gray-800 dark:text-white/90">Stored strategies</h3>
          <p className="text-theme-xs text-gray-500 dark:text-gray-400">
            {total.toLocaleString()} {[coin, tf, signal, profitable ? "profitable only" : ""].some(Boolean) ? "match" : "stored strategies"}
            {rows.length < total ? ` · showing top ${rows.length} by ${STRATEGY_SORTS[sort]}` : ` · sorted by ${STRATEGY_SORTS[sort]}`}
            {/* A partial index must NOT be captioned as the whole store: the
                sweep measures pairs faster than they are indexed, and "648,181
                stored strategies" while 40 pairs are still queued is a false
                label on a true number. */}
            {idx && (idx.behind > 0 || idx.syncing) ? (
              <span className="text-warning-600 dark:text-warning-400">
                {" · "}indexing {idx.pairs_indexed.toLocaleString()} of{" "}
                {idx.pairs_on_disk.toLocaleString()} measured pairs — this list is
                still filling in
              </span>
            ) : null}
            {[coin, tf, signal].filter(Boolean).length ? ` · filters: ${[coin, tf, signal].filter(Boolean).join(" · ")}` : ""}
            {profitable ? " · profitable only" : " · losers included"}
          </p>
        </div>
        <div className="ml-auto flex flex-wrap gap-2">
          <select className={sel} value={coin} onChange={(e) => setCoin(e.target.value)} aria-label="Coin">
            <option value="">all coins</option>
            {facets.coins.map((c) => <option key={c}>{c}</option>)}
          </select>
          <select className={sel} value={tf} onChange={(e) => setTf(e.target.value)} aria-label="Timeframe">
            <option value="">all timeframes</option>
            {facets.tfs.map((t) => <option key={t}>{t}</option>)}
          </select>
          <select className={sel} value={signal} onChange={(e) => setSignal(e.target.value)} aria-label="Signal">
            <option value="">all signals</option>
            {facets.signals.map((s) => <option key={s}>{s}</option>)}
          </select>
          {/* the operator asked to rank by win rate (2026-08-26): profit alone
              cannot find a 70%-win configuration in millions of rows */}
          <select className={sel} value={sort}
                  onChange={(e) => setSort(e.target.value as StrategySort)}
                  aria-label="Sort by">
            {Object.entries(STRATEGY_SORTS).map(([k, label]) => (
              <option key={k} value={k}>sort: {label}</option>
            ))}
          </select>
          <label className="flex h-10 items-center gap-2 text-theme-sm text-gray-700 dark:text-gray-300">
            <input type="checkbox" checked={profitable} onChange={(e) => setProfitable(e.target.checked)} className="h-4 w-4 accent-brand-500" />
            profitable only
          </label>
        </div>
      </div>
      {err && <p className="px-5 pt-2 text-theme-sm text-error-500">{err}</p>}
      <div className="max-h-[480px] max-w-full overflow-auto p-2">
        <Table>
          <TableHeader className="sticky top-0 border-b border-gray-100 bg-white dark:border-white/[0.05] dark:bg-gray-900">
            <TableRow>
              {["id", "coin", "tf", "signal", "th%", "SL%", "TP%", "sizing", "lev", "margin $", "PROFIT $", "win %", "trades", "W", "L", "green", "dip $"].map((h) => (
                <TableCell key={h} isHeader
                  className={`px-3 py-3 text-theme-xs font-medium text-start ${
                    h === STRATEGY_SORTS[sort]
                      ? "text-brand-600 dark:text-brand-400"
                      : "text-gray-500 dark:text-gray-400"}`}>
                  {h}{h === STRATEGY_SORTS[sort] ? " ↓" : ""}
                </TableCell>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
            {rows.map((r) => (
              <TableRow key={r.id} onClick={() => view(r)}
                className={`cursor-pointer hover:bg-gray-50 dark:hover:bg-white/[0.03] ${open?.id === r.id ? "bg-brand-50 dark:bg-brand-500/10" : ""}`}>
                <TableCell className="px-3 py-2 font-mono text-theme-xs text-brand-600 dark:text-brand-400">#{r.id}</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm font-medium text-gray-800 dark:text-white/90">{r.coin}</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{r.tf}</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm font-medium text-gray-800 dark:text-white/90">{r.signal}</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{r.th ?? 0}</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{r.sl}</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{r.tp}</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{r.sizing}</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{r.lev ?? 20}x</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{r.base ?? 5} ({r.notional ?? 100} ntl)</TableCell>
                <TableCell className={`px-3 py-2 text-theme-sm font-semibold ${(r.profit ?? 0) >= 0 ? "text-success-600" : "text-error-500"}`}>{fmtMoney(r.profit)}</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{r.winrate?.toFixed(2)}</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{r.trades}</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm text-success-600">{r.wins}</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm text-error-500">{r.losses}</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{r.green ?? "—"}/{r.months ?? "—"}</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{r.dd?.toFixed(2) ?? "—"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {open && (
        <div className="border-t border-gray-100 px-5 py-4 dark:border-white/[0.05]">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <span className="font-mono text-theme-sm text-brand-600 dark:text-brand-400">#{open.id}</span>
            <span className="text-theme-sm font-medium text-gray-800 dark:text-white/90">
              {open.coin} {open.tf} {open.signal} · SL {open.sl}% / TP {open.tp}% · {open.sizing}
            </span>
            {busy && <Badge size="sm" color="info">rebuilding trades…</Badge>}
            {trades && trades.log.length > 0 && (
              <>
                <Badge size="sm" color="primary">{trades.trades} trades</Badge>
                <Badge size="sm" color="success">{trades.wins} WIN</Badge>
                <Badge size="sm" color="error">{trades.losses} LOSE</Badge>
                <Badge size="sm" color={(trades.profit ?? 0) >= 0 ? "success" : "error"}>
                  TOTAL {fmtMoney(trades.profit ?? logSum)} USDT
                </Badge>
              </>
            )}
          </div>
          {drift && (
            <p className="mb-2 text-theme-sm text-warning-600">
              These trades total {fmtMoney(trades?.profit ?? logSum)} but the stored row says {fmtMoney(open.profit)} —
              the candle store has grown since the row was measured. Run BACKTEST to refresh it.
            </p>
          )}
          {trades && trades.why && !trades.log.length && (
            <p className="text-theme-sm text-gray-500 dark:text-gray-400">{trades.why}</p>
          )}
          {trades && trades.log.length > 0 && (
            <div className="max-h-80 max-w-full overflow-auto">
              <Table>
                <TableHeader className="sticky top-0 bg-white dark:bg-gray-900">
                  <TableRow>
                    {["opened", "closed", "side", "closed by", "entry", "exit", "rung", "margin $", "funding $", "W/L", "pnl $", "running $"].map((h) => (
                      <TableCell key={h} isHeader className="px-3 py-2 text-theme-xs font-medium text-gray-500 text-start dark:text-gray-400">{h}</TableCell>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
                  {trades.log.map((t, i) => (
                    <TableRow key={i}>
                      <TableCell className="px-3 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{t["entry time"]}</TableCell>
                      <TableCell className="px-3 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{t["exit time"]}</TableCell>
                      <TableCell className="px-3 py-1.5 text-theme-xs text-gray-700 dark:text-gray-300">{t.side}</TableCell>
                      <TableCell className="px-3 py-1.5 text-theme-xs font-medium text-gray-700 dark:text-gray-300">{t.why}</TableCell>
                      <TableCell className="px-3 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{t.entry}</TableCell>
                      <TableCell className="px-3 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{t.exit}</TableCell>
                      <TableCell className="px-3 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{t.step}</TableCell>
                      <TableCell className="px-3 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{t["margin $"]}</TableCell>
                      <TableCell className="px-3 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{t["funding $"] ?? 0}</TableCell>
                      <TableCell className={`px-3 py-1.5 text-theme-xs font-semibold ${t["WIN/LOSE"] === "WIN" ? "text-success-600" : "text-error-500"}`}>{t["WIN/LOSE"]}</TableCell>
                      <TableCell className={`px-3 py-1.5 text-theme-xs ${t["pnl $"] >= 0 ? "text-success-600" : "text-error-500"}`}>{fmtMoney(t["pnl $"])}</TableCell>
                      <TableCell className="px-3 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{fmtMoney(t["running total $"])}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <p className="mt-2 text-theme-xs text-gray-500 dark:text-gray-400">
                Log sum {fmtMoney(logSum)} USDT over {trades.log.length} trades — losers cost{" "}
                {fmtMoney(trades.log.filter((t) => t["pnl $"] <= 0).reduce((a, t) => a + t["pnl $"], 0))}, wins earned{" "}
                {fmtMoney(trades.log.filter((t) => t["pnl $"] > 0).reduce((a, t) => a + t["pnl $"], 0))}.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
