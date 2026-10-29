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
  // Part 2b: the kit's remaining columns (v3_page.check_row)
  per_day?: number | null; target?: string | null; stop?: string | null;
  target_pct?: string | null; stop_pct?: string | null; lev?: string | null;
  // the final fix wave: wins and losses a day (kit item 6), and beside the verdict the share of
  // its entries and exits settled without their own minute's book (COVERAGE FIRST)
  wins_per_day?: number | null; losses_per_day?: number | null;
  cost_unseen?: string | null; cost_older?: string | null; cost_share?: number | null;
};
export type Check = {
  state: string; words?: string; coins?: string[]; risk_usd?: number | null; runs?: number | null;
  judged_at?: number | null; plan_end?: number | null; plan_id?: string | null;
  lev?: [number, number] | null; notional?: [number, number] | null; verdicts?: CheckRow[] | number;
  // the verdict store's (v3_page.store_view): combinations tried, the plan's coins, the run's name,
  // and how many of the plan's coins were not judged, by why
  tried?: number | null; plan_coins?: number | null; name?: string | null;
  not_judged?: Record<string, number>;
  // every coin of the plan not judged, one line each ("COIN: why"), by bucket; the accounts that
  // failed (a download, a refused share, machines) and how many coins the run was sent
  not_judged_coins?: Record<string, string[]>;
  accounts?: Record<string, string[]>;
  dispatched?: number | null;
} | null;

/** "check": the 3-coin check on this PC; "stored": the verdict store a GitHub run published. */
export type CheckKind = "check" | "stored";

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
// why a coin of the plan was not judged, in words (v3_verdicts' `not_judged` keys)
const NOT_JUDGED: Record<string, string> = {
  not_reached: "not reached", failed: "failed", unmeasured: "claimed by a machine and not finished",
  left_out: "left out by the machine", refused_records: "record refused at landing",
  downloads_failed: "on an account whose download failed", shares_refused: "on an account that refused its share",
  machines_refused: "on an account whose machines refused to measure",
  other_records: "measured under another plan or risk", no_walk: "no timeframe measured",
  not_dispatched: "not sent (a pilot)",
};
const ACCOUNTS: Record<string, string> = {
  downloads_failed: "Download failed", shares_refused: "Share refused", machines_refused: "Machines refused",
  runs_without_artifact: "No artifact",
  unreadable_records: "Unreadable record",
};
function money(v: number): string {
  return `${v >= 0 ? "+" : "−"}$${Math.abs(v).toFixed(2)}`;
}

export default function V3Check({ check, kind = "check" }: { check: Check; kind?: CheckKind }) {
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
  const planCoins = check.plan_coins ?? 0;
  // every word of the heading from the file: a store judged on fewer coins than its plan holds is a
  // pilot, never the proof
  // every word of the heading from the file. A PILOT is a run that was SENT fewer coins than the plan
  // holds; a full run with gaps says how many coins were not judged, never "pilot"
  const pilot = check.dispatched != null && check.dispatched < planCoins;
  const heading = kind === "stored"
    ? (pilot
      ? `Pilot — ${coins.length} of the plan's ${planCoins} coins, not the proof`
      : coins.length < planCoins
        ? `Full run — ${planCoins - coins.length} of ${planCoins} coins not judged`
        : `Every idea's verdict — ${coins.length} coins`)
    : check.state === "ok"
      ? `Check only — ${coins.length} coin${coins.length === 1 ? "" : "s"}, not the proof`
      : "Check only — not the proof";
  if (kind === "check" && check.state !== "ok") {
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
  // one leverage is "20x", as the results page prints it
  const lev = check.lev ? (check.lev[0] === check.lev[1] ? `${check.lev[0]}x` : `${check.lev[0]}x–${check.lev[1]}x`) : "none traded";
  const notional = check.notional ? `$${check.notional[0].toFixed(0)}–$${check.notional[1].toFixed(0)}` : "none traded";

  return (
    <div className="mt-4">
      <h4 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">{heading}</h4>
      <p className="mt-1 max-w-3xl text-theme-xs text-gray-500 dark:text-gray-400">
        {kind === "stored" ? `${coins.length} of the plan's ${planCoins} coins judged` : `${coinWords(coins)} judged`} {fmtWhen(check.judged_at)} at {risk} a
        trade, {check.runs ?? "an unrecorded number of"} random runs a combination
        {kind === "stored" ? `, ${check.tried ?? "an unrecorded number of"} combinations tried` : "; the proof needs every coin (step 2b on GitHub)"}.
        {" "}{passed} of {rows.length} verdicts passed.
        {kind === "stored" && check.not_judged && Object.keys(check.not_judged).length > 0 &&
          ` Not judged: ${Object.entries(check.not_judged).map(([k, n]) => `${n} ${NOT_JUDGED[k] ?? k}`).join(", ")}.`}
      </p>
      {kind === "stored" && check.accounts && Object.entries(check.accounts).map(([k, xs]) => (
        <p key={k} className="mt-1 max-w-3xl text-theme-xs text-warning-600 dark:text-warning-400">
          {ACCOUNTS[k] ?? k}: {xs.join("; ")}
        </p>
      ))}
      {kind === "stored" && check.not_judged_coins && Object.entries(check.not_judged_coins).map(([k, xs]) => (
        <details key={k} className="mt-1 max-w-3xl text-theme-xs text-gray-500 dark:text-gray-400">
          <summary className="cursor-pointer">{xs.length} {NOT_JUDGED[k] ?? k}</summary>
          <ul className="ml-4 list-disc">{xs.map((x) => <li key={x}>{x}</li>)}</ul>
        </details>
      ))}
      <p className="mt-1 max-w-3xl text-theme-xs text-gray-500 dark:text-gray-400">
        Universe plan {check.plan_id ?? "not recorded"}, ending {fmtWhen(check.plan_end != null ? check.plan_end / 1000 : null)}
        {" "}· {rows.length} judged groups
        {" "}· leverage {lev} · {notional} of coin a trade (margin = the coin bought ÷ its leverage).
        {" "}Typical cost: the share of each verdict&apos;s entries and exits settled without their own minute&apos;s order
        book (a coin&apos;s usual cost paid, or a post-only check that could not be made) - a range when some orders
        placed with no book never filled.
      </p>
      <div className="mt-2 overflow-x-auto">
        <Table>
          <TableHeader className="border-b border-gray-100 dark:border-white/[0.05]">
            <TableRow>
              {head("id", "ID")}{head("family", "Idea")}{head("tf", "Timeframe")}{head("filter", "Filter")}
              {head("setting", "Setting chosen")}{head("verdict", "Verdict")}{head("profit", "PROFIT (total $)")}
              {head("target", "Target (TP rule)")}{head("target_pct", "Target size")}{head("stop", "Stop (SL rule)")}
              {head("stop_pct", "Stop size")}{head("lev", "Leverage")}{head("trades", "Unseen trades")}{head("per_day", "Trades a day")}
              {head("wins", "Won / lost")}{head("wins_per_day", "Won / lost a day")}{head("win_rate", "Win rate")}
              {head("worst_run_usd", "Worst losing run")}{head("random_median_trades", "Random runs' median trades vs the real run's")}
              {head("cost_share", "Typical cost, unseen days")}{head("cost_older", "Typical cost, older days")}
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
                {cell(r, r.profit != null ? money(r.profit) : null)}
                {cell(r, r.target ?? null)}{cell(r, r.target_pct ?? null)}{cell(r, r.stop ?? null)}
                {cell(r, r.stop_pct ?? null)}{cell(r, r.lev ?? null)}
                {cell(r, r.trades)}{cell(r, r.per_day ?? null)}
                {cell(r, r.wins != null && r.losses != null ? `${r.wins} / ${r.losses}` : null)}
                {cell(r, r.wins_per_day != null && r.losses_per_day != null ? `${r.wins_per_day.toFixed(2)} / ${r.losses_per_day.toFixed(2)}` : null)}
                {cell(r, r.win_rate != null ? `${(r.win_rate * 100).toFixed(1)}%` : null)}
                {cell(r, r.worst_run_usd != null && r.worst_run_trades != null
                  ? (r.worst_run_trades ? `${money(r.worst_run_usd)} over ${r.worst_run_trades} trade${r.worst_run_trades === 1 ? "" : "s"}` : "no losses")
                  : null)}
                {cell(r, r.random_median_trades != null && r.real_trades != null ? `${r.random_median_trades} vs ${r.real_trades}` : null)}
                {cell(r, r.cost_unseen ?? null)}{cell(r, r.cost_older ?? null)}
                <TableCell className={`${td} whitespace-normal min-w-64`}>{r.why}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <PageButtons cur={page} pages={pages} goto={setPage} what={kind === "stored" ? "Verdicts" : "Check verdicts"} />
    </div>
  );
}
