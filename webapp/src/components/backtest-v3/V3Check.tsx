"use client";
/** THE 3-COIN CHECK on the Backtest v3 tab (operator, Oct 27, 2026: "go" to
 * "both"). The verdicts `python -m tradingagents.v3_research` judged on this
 * PC, read with what they were judged under (`v3_page.check`): a check of the
 * machinery on a few coins, never the proof, which needs every coin (step 2b,
 * on GitHub). Every word above the table is derived from the file - the
 * coins, the risk, the runs, the date - and every cell of every row says
 * something: a number, or why there is none (`blank`, from the server).
 */
import { type ReactNode, useMemo, useState } from "react";
import { fmtWhen } from "@/lib/api";
import PageButtons from "@/components/common/PageButtons";
import { Table, TableBody, TableCell, TableHeader, TableRow } from "@/components/ui/table";

export type CheckRow = {
  id: string; family: string; tf: string; filter: string; setting: string | null;
  passed: boolean; failed: string; verdict: string; trades: number | null; wins: number | null;
  losses: number | null; win_rate: number | null; profit: number | null;
  worst_run_usd: number | null; worst_run_trades: number | null;
  random_median_trades: number | null; real_trades: number | null; why: string; blank: string;
};
export type Check = {
  state: string; words?: string; coins?: string[]; risk_usd?: number | null; runs?: number | null;
  judged_at?: number | null; plan_end?: number | null; plan_id?: string | null;
  lev?: [number, number] | null; notional?: [number, number] | null; verdicts?: CheckRow[] | number;
} | null;

const PER_PAGE = 10;           // Auto Trade's own page size
const th = "px-3 py-2 text-left text-theme-xs font-medium text-gray-500 dark:text-gray-400";
const td = "whitespace-nowrap px-3 py-2 text-theme-sm tabular-nums text-gray-700 dark:text-gray-300";
const why = "whitespace-nowrap px-3 py-2 text-theme-xs italic text-gray-400 dark:text-gray-500";

type Key = keyof CheckRow;

/** "BTC, ETH and XAU": each coin's name before its quote currency, in the file's order. */
function coinWords(coins: string[]): string {
  const names = coins.map((c) => c.split("_")[0]);
  if (names.length <= 1) return names.join("");
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}
function money(v: number): string {
  return `${v >= 0 ? "+" : "−"}$${Math.abs(v).toFixed(2)}`;
}

export default function V3Check({ check }: { check: Check }) {
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState<{ key: Key; dir: 1 | -1 } | null>(null);
  const rows = useMemo(() => (Array.isArray(check?.verdicts) ? check.verdicts : []), [check]);
  const sorted = useMemo(() => {
    if (!sort) return rows;
    const out = [...rows];
    out.sort((a, b) => {
      const x = a[sort.key], y = b[sort.key];
      if (x == null && y == null) return 0;
      if (x == null) return 1;                       // a row with no number sorts last
      if (y == null) return -1;
      if (typeof x === "number" && typeof y === "number") return (x - y) * sort.dir;
      return String(x).localeCompare(String(y)) * sort.dir;
    });
    return out;
  }, [rows, sort]);
  if (!check) return null;
  const coins = check.coins ?? [];
  const heading = check.state === "ok"
    ? `Check only — ${coins.length} coin${coins.length === 1 ? "" : "s"}, not the proof`
    : "Check only — not the proof";
  if (check.state !== "ok") {
    return (
      <div className="mt-4">
        <h4 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">{heading}</h4>
        <p className="mt-1 max-w-3xl text-theme-xs text-gray-500 dark:text-gray-400">{check.words}</p>
      </div>
    );
  }
  const passed = rows.filter((r) => r.passed).length;
  const pages = Math.max(1, Math.ceil(sorted.length / PER_PAGE));
  const shown = sorted.slice((page - 1) * PER_PAGE, page * PER_PAGE);
  const sortBy = (key: Key) => {
    setSort((s) => ({ key, dir: s?.key === key ? (s.dir === 1 ? -1 : 1) : 1 }));
    setPage(1);
  };
  const head = (key: Key, label: string) => (
    <TableCell isHeader className={`${th} cursor-pointer select-none`} onClick={() => sortBy(key)} title="Click to sort">
      {label}{sort?.key === key ? (sort.dir === 1 ? " ▲" : " ▼") : ""}
    </TableCell>
  );
  const cell = (r: CheckRow, v: ReactNode | null) =>
    v == null ? <TableCell className={why}>{r.blank || "not recorded"}</TableCell> : <TableCell className={td}>{v}</TableCell>;
  const risk = check.risk_usd != null ? `$${check.risk_usd.toFixed(2)}` : "an unrecorded risk";
  const lev = check.lev ? `${check.lev[0]}x–${check.lev[1]}x` : "none traded";
  const notional = check.notional ? `$${check.notional[0].toFixed(0)}–$${check.notional[1].toFixed(0)}` : "none traded";

  return (
    <div className="mt-4">
      <h4 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">{heading}</h4>
      <p className="mt-1 max-w-3xl text-theme-xs text-gray-500 dark:text-gray-400">
        {coinWords(coins)} judged {fmtWhen(check.judged_at)} at {risk} a trade, {check.runs ?? "an unrecorded number of"} random
        runs a combination; the proof needs every coin (step 2b on GitHub). {passed} of {rows.length} verdicts passed.
      </p>
      <p className="mt-1 max-w-3xl text-theme-xs text-gray-500 dark:text-gray-400">
        Universe plan {check.plan_id ?? "not recorded"}, ending {fmtWhen(check.plan_end != null ? check.plan_end / 1000 : null)}
        {" "}· {rows.length} judged groups
        {" "}· leverage {lev} · {notional} of coin a trade (margin = the coin bought ÷ its leverage).
      </p>
      <div className="mt-2 overflow-x-auto">
        <Table>
          <TableHeader className="border-b border-gray-100 dark:border-white/[0.05]">
            <TableRow>
              {head("id", "ID")}{head("family", "Idea")}{head("tf", "Timeframe")}{head("filter", "Filter")}
              {head("setting", "Setting chosen")}{head("verdict", "Verdict")}{head("trades", "Unseen trades")}
              {head("wins", "Won / lost")}{head("win_rate", "Win rate")}{head("profit", "PROFIT (total $)")}
              {head("worst_run_usd", "Worst losing run")}{head("random_median_trades", "Random runs' median trades vs the real run's")}
              {head("why", "Why")}
            </TableRow>
          </TableHeader>
          <TableBody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
            {shown.map((r) => (
              <TableRow key={r.id}>
                <TableCell className={`${td} font-medium`}>#{r.id}</TableCell>
                <TableCell className={td}>{r.family}</TableCell>
                <TableCell className={td}>{r.tf}</TableCell>
                <TableCell className={td}>{r.filter}</TableCell>
                {cell(r, r.setting)}
                <TableCell className={`${td} font-semibold ${r.passed ? "text-success-600 dark:text-success-400" : "text-error-600 dark:text-error-400"}`}>{r.verdict}</TableCell>
                {cell(r, r.trades)}
                {cell(r, r.wins != null && r.losses != null ? `${r.wins} / ${r.losses}` : null)}
                {cell(r, r.win_rate != null ? `${(r.win_rate * 100).toFixed(1)}%` : null)}
                {cell(r, r.profit != null ? money(r.profit) : null)}
                {cell(r, r.worst_run_usd != null && r.worst_run_trades != null
                  ? (r.worst_run_trades ? `${money(r.worst_run_usd)} over ${r.worst_run_trades} trade${r.worst_run_trades === 1 ? "" : "s"}` : "no losses")
                  : null)}
                {cell(r, r.random_median_trades != null && r.real_trades != null ? `${r.random_median_trades} vs ${r.real_trades}` : null)}
                <TableCell className={`${td} whitespace-normal min-w-64`}>{r.why}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <PageButtons cur={page} pages={pages} goto={setPage} what="Check verdicts" />
    </div>
  );
}
