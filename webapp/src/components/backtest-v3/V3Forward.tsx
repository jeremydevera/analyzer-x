"use client";
/** THE FORWARD TEST on the Backtest v3 tab (operator, Nov 05, 2026: "go", to running the
 * forward-tested strategies in practice). Every v3 strategy that was profitable on 2025's unseen
 * days and chosen again by 2026's older days, walked to now each hour by the research's own engine
 * (tradingagents/v3_forward.py) - only the trades it opened AFTER the day the list was made, so
 * nothing here was seen when it was chosen. It places no order. Every number is the server's; the
 * words above the table are derived from the file (the start, the last pass, the counts).
 */
import { Fragment, useEffect, useMemo, useState } from "react";
import { API_BASE, fmtWhenMs } from "@/lib/api";
import PageButtons from "@/components/common/PageButtons";
import { Table, TableBody, TableCell, TableHeader, TableRow } from "@/components/ui/table";

type Trade = { side: string; entry_ms: number; entry: number; exit_ms: number; exit: number;
  why: string; pnl: number; leverage: number; notional: number; measured_exit: boolean };
type Row = { id: string; coin: string; family: string; tf: string; filter: string; setting: string;
  target: string; stop: string; profit: number; wins: number; losses: number;
  worst_run_usd: number; worst_run_trades: number; closed: Trade[]; open: Trade[];
  carried: number; stale?: boolean };
type State = { ready: boolean; why?: string; since?: string; ticked?: string; took_s?: number;
  risk_usd?: number; listed?: number; failed?: string[];
  summary?: { trades: number; wins: number; losses: number; profit: number; worst_run_usd: number;
    worst_run_trades: number; open: number; open_pnl: number; carried: number; in_profit: number;
    strategies: number };
  rows?: Row[] };

const PER_PAGE = 10;
const th = "px-3 py-2 text-left text-theme-xs font-medium text-gray-500 dark:text-gray-400";
const td = "whitespace-nowrap px-3 py-2 text-theme-sm tabular-nums text-gray-700 dark:text-gray-300";
type Key = "id" | "coin" | "family" | "filter" | "setting" | "profit" | "trades" | "wins" |
  "win_rate" | "worst_run_usd" | "open";

function money(v: number): string {
  return `${v >= 0 ? "+" : "−"}$${Math.abs(v).toFixed(2)}`;
}
function val(r: Row, k: Key): number | string {
  if (k === "trades") return r.closed.length;
  if (k === "open") return r.open.length;
  if (k === "win_rate") return r.closed.length ? r.wins / r.closed.length : -1;
  return r[k] as number | string;
}
const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;

export default function V3Forward() {
  const [st, setSt] = useState<State | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState<{ key: Key; dir: 1 | -1 }>({ key: "profit", dir: -1 });
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    const load = () => fetch(`${API_BASE}/api/v3/forward`, { cache: "no-store" })
      .then((r) => { if (!r.ok) throw new Error(`/api/v3/forward -> HTTP ${r.status}`); return r.json(); })
      .then((d) => { if (live) { setSt(d); setErr(null); } })
      .catch((e) => { if (live) setErr(String(e.message ?? e)); });
    load();
    const t = setInterval(load, 60_000);
    return () => { live = false; clearInterval(t); };
  }, []);
  const rows = useMemo(() => {
    const out = [...(st?.rows ?? [])];
    out.sort((a, b) => {
      const x = val(a, sort.key), y = val(b, sort.key);
      if (typeof x === "number" && typeof y === "number") return (x - y) * sort.dir;
      return String(x).localeCompare(String(y)) * sort.dir;
    });
    return out;
  }, [st, sort]);
  const title = "Forward test — the forward-tested strategies since the day they were chosen";
  if (err) return <div className="mt-4"><h4 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">{title}</h4><p className="mt-1 text-theme-xs text-error-600">Could not read it: {err}</p></div>;
  if (!st) return null;
  if (!st.ready || !st.summary) {
    return <div className="mt-4"><h4 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">{title}</h4><p className="mt-1 text-theme-xs text-gray-500 dark:text-gray-400">{st.why}</p></div>;
  }
  const s = st.summary;
  const pages = Math.max(1, Math.ceil(rows.length / PER_PAGE));
  const shown = rows.slice((page - 1) * PER_PAGE, page * PER_PAGE);
  const sortBy = (key: Key) => { setSort((o) => ({ key, dir: o.key === key ? (o.dir === 1 ? -1 : 1) : -1 })); setPage(1); };
  const head = (key: Key, label: string) => (
    <TableCell isHeader className={`${th} cursor-pointer select-none`} onClick={() => sortBy(key)} title="Click to sort">
      {label}{sort.key === key ? (sort.dir === 1 ? " ▲" : " ▼") : ""}
    </TableCell>
  );
  const lev = [...new Set(rows.flatMap((r) => [...r.closed, ...r.open].map((t) => t.leverage)))].sort((a, b) => a - b);
  const levWords = lev.length ? (lev[0] === lev[lev.length - 1] ? `${lev[0]}x` : `${lev[0]}x–${lev[lev.length - 1]}x`) : "none traded yet";
  return (
    <div className="mt-4">
      <h4 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">{title}</h4>
      <p className="mt-1 max-w-3xl text-theme-xs text-gray-500 dark:text-gray-400">
        {plural(st.listed ?? rows.length, "strategy")} (profitable on 2025&apos;s unseen days and chosen again by
        2026&apos;s older days), followed since {st.since}: every trade they opened after that, walked each hour by
        the same v3 engine at ${(st.risk_usd ?? 5).toFixed(2)} risk a trade, every cost paid; leverage {levWords}. Last pass {st.ticked} ({st.took_s} s). No order is placed.
      </p>
      <p className="mt-1 max-w-3xl text-theme-sm text-gray-700 dark:text-gray-300">
        <b>Closed since the start: {plural(s.trades, "trade")}, {s.wins} won / {s.losses} lost,{" "}
          <span className={s.profit >= 0 ? "text-success-600 dark:text-success-400" : "text-error-600 dark:text-error-400"}>{money(s.profit)}</span></b>
        {s.trades > 0 && `; worst losing run ${s.worst_run_trades ? `${money(s.worst_run_usd)} over ${plural(s.worst_run_trades, "trade")}` : "none"}`}
        ; {plural(s.open, "trade")} open now ({money(s.open_pnl)} if closed at the last price)
        {s.carried > 0 && `; ${s.carried} still in a trade from before the start (not counted)`}.
      </p>
      {(st.failed ?? []).length > 0 && (
        <p className="mt-1 max-w-3xl text-theme-xs text-warning-600 dark:text-warning-400">
          Not read this pass (showing the last pass): {st.failed!.join("; ")}
        </p>
      )}
      <div className="mt-2 overflow-x-auto">
        <Table>
          <TableHeader className="border-b border-gray-100 dark:border-white/[0.05]">
            <TableRow>
              {head("id", "ID")}{head("coin", "Coin")}{head("family", "Idea")}
              <TableCell isHeader className={th}>Timeframe</TableCell>
              {head("filter", "Filter")}{head("setting", "Setting")}{head("profit", "PROFIT (total $)")}
              <TableCell isHeader className={th}>Target (TP rule)</TableCell><TableCell isHeader className={th}>Stop (SL rule)</TableCell>
              {head("trades", "Closed trades")}{head("wins", "Won / lost")}{head("win_rate", "Win rate")}
              {head("worst_run_usd", "Worst losing run")}{head("open", "Open now")}
            </TableRow>
          </TableHeader>
          <TableBody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
            {shown.map((r) => (
              <Fragment key={r.id}>
                <TableRow className="cursor-pointer hover:bg-gray-50 dark:hover:bg-white/[0.03]" onClick={() => setOpen(open === r.id ? null : r.id)}>
                  <TableCell className={`${td} font-medium`}>#{r.id}{r.stale ? " (last pass)" : ""}</TableCell>
                  <TableCell className={td}>{r.coin.replace("_USDT", "")}</TableCell>
                  <TableCell className={td}>{r.family.replace("v3_", "")}</TableCell>
                  <TableCell className={td}>{r.tf}</TableCell>
                  <TableCell className={td}>{r.filter}</TableCell>
                  <TableCell className={td}>{r.setting}</TableCell>
                  <TableCell className={`${td} font-semibold`}>{r.closed.length ? money(r.profit) : "no trade yet"}</TableCell>
                  <TableCell className={`${td} whitespace-normal min-w-48`}>{r.target}</TableCell>
                  <TableCell className={`${td} whitespace-normal min-w-48`}>{r.stop}</TableCell>
                  <TableCell className={td}>{r.closed.length}</TableCell>
                  <TableCell className={td}>{r.wins} / {r.losses}</TableCell>
                  <TableCell className={td}>{r.closed.length ? `${((r.wins / r.closed.length) * 100).toFixed(1)}%` : "—"}</TableCell>
                  <TableCell className={td}>{r.worst_run_trades ? `${money(r.worst_run_usd)} over ${plural(r.worst_run_trades, "trade")}` : "no losses"}</TableCell>
                  <TableCell className={td}>{r.open.length ? `${r.open.length} (${money(r.open.reduce((a, t) => a + t.pnl, 0))})` : r.carried ? "in a trade from before" : "0"}</TableCell>
                </TableRow>
                {open === r.id && (
                  <TableRow>
                    <TableCell colSpan={14} className="px-3 py-2 text-theme-xs text-gray-600 dark:text-gray-300">
                      {r.closed.length + r.open.length === 0 ? "No trade opened since the start." : (
                        <>
                          <ul>
                            {[...r.closed, ...r.open].map((t, i) => (
                              <li key={i} className="tabular-nums">
                                {i + 1}. {t.side} {fmtWhenMs(t.entry_ms)} at {t.entry} → {t.why === "END" ? `still open, last ${t.exit}` : `${fmtWhenMs(t.exit_ms)} at ${t.exit} (${t.why})`}: {money(t.pnl)} · {t.leverage}x · ${t.notional.toFixed(2)} of coin
                              </li>
                            ))}
                          </ul>
                          <p className="mt-1 font-semibold">TOTAL PROFIT (closed): {money(r.profit)} over {plural(r.closed.length, "trade")}</p>
                        </>
                      )}
                    </TableCell>
                  </TableRow>
                )}
              </Fragment>
            ))}
          </TableBody>
        </Table>
      </div>
      <PageButtons cur={page} pages={pages} goto={setPage} what="Forward-tested strategies" />
    </div>
  );
}
