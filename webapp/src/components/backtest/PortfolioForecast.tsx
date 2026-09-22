"use client";
/** THE FORECAST FOR THE ACCOUNT — every switched-on row replayed TOGETHER.
 *
 * A stored backtest row is measured alone: every signal taken, on a coin
 * nothing else is holding, at one saved cost. The account does none of that,
 * which is how 80 rows read 97.3% in Backtest v2 and 72.0% on the practice
 * account beside it (operator, Sep 23, 2026: *"i want forecast to be 10/10"*).
 * This panel prints what the whole deployment would have done as ONE account
 * — the runner's own gates, the venue's own book readings, exits by the
 * minute — and, underneath, the same replay cut to the days the practice
 * account has really been trading, beside what it really did. The gap between
 * those two lines is how far the forecast can be trusted, and it is printed,
 * never hidden.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  fmtWhenMs, ForecastRow, ForecastSide, PortfolioForecast as Forecast, storeApi,
} from "@/lib/api";
import StoreBadge from "@/components/StoreBadge";
import { Table, TableBody, TableCell, TableHeader, TableRow } from "@/components/ui/table";

/** what each refusal means, in the words the operator uses */
const REFUSAL_WORDS: Record<string, string> = {
  cost_gate: "the fees and spread would have eaten half the target",
  book_unknown: "the venue's book was not recorded near that minute, so the cost was unknown",
  coin_busy: "that coin was already being traded",
  opposite_side: "another row was already trading that coin the other way",
  no_candles: "no one-minute candles for that coin yet",
  bad_minutes: "a minute is missing from that coin's candles",
  formula_error: "the formula could not run",
  no_price: "no price on the next bar",
  gate_blocked: "the fees and spread would have eaten half the target",
  blocked: "that coin was already being traded",
  stale_skip: "the signal was too old by the time it was seen",
  chase_skip: "the price had already run away",
  capital_blocked: "the wallet could not fund it",
  size_capped: "the venue would not take the whole order",
};

const money = (v: number | null | undefined) =>
  v == null ? "—" : `${v < 0 ? "−" : "+"}$${Math.abs(v).toFixed(2)}`;
const pct = (v: number) => `${v.toFixed(2)}%`;

type SortKey = keyof Pick<ForecastRow,
  "pnl" | "trades" | "wins" | "losses" | "win_rate" | "worst_run" | "signals" | "cost_refused">;

export default function PortfolioForecast() {
  const S = useMemo(() => storeApi("v2"), []);
  const [d, setD] = useState<Forecast | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [sort, setSort] = useState<SortKey>("pnl");
  const [asc, setAsc] = useState(false);
  const [showLog, setShowLog] = useState<string | null>(null);

  const load = useCallback((fresh = false) => {
    setBusy(true);
    S.portfolio("demo", fresh).then((x) => { setD(x); setErr(""); })
      .catch((e) => setErr(String(e))).finally(() => setBusy(false));
  }, [S]);
  useEffect(() => { load(); }, [load]);

  const rows = useMemo(() => {
    const list = d?.account?.rows ?? [];
    const dir = asc ? 1 : -1;
    return [...list].sort((a, b) => ((a[sort] as number) - (b[sort] as number)) * dir);
  }, [d, sort, asc]);

  const head = (label: string, key?: SortKey) => (
    <TableCell key={label} isHeader
      className={`px-3 py-2 text-theme-xs font-medium text-gray-500 text-start dark:text-gray-400 ${key ? "cursor-pointer select-none" : ""}`}>
      <span onClick={() => { if (!key) return; if (sort === key) setAsc(!asc); else { setSort(key); setAsc(false); } }}>
        {label}{key && sort === key ? (asc ? " ▲" : " ▼") : ""}
      </span>
    </TableCell>
  );

  if (err) {
    return (
      <div className="rounded-2xl border border-gray-200 bg-white p-5 text-theme-xs text-error-600 dark:border-white/[0.05] dark:bg-white/[0.03]">
        the account forecast could not be read: {err}
      </div>
    );
  }
  if (!d) {
    return (
      <div className="rounded-2xl border border-gray-200 bg-white p-5 text-theme-xs text-gray-500 dark:border-white/[0.05] dark:bg-white/[0.03]">
        replaying every switched-on row together — a few seconds…
      </div>
    );
  }
  if (d.why || !d.account) {
    return (
      <div className="rounded-2xl border border-gray-200 bg-white p-5 text-theme-xs text-gray-500 dark:border-white/[0.05] dark:bg-white/[0.03]">
        {d.why ?? "nothing to replay yet"}
      </div>
    );
  }

  const a: ForecastSide = d.account;
  const c = d.checked;
  const act = d.actual;
  const days = a.window.first_ms && a.window.last_ms
    ? Math.round((a.window.last_ms - a.window.first_ms) / 86_400_000) : 0;
  const refusedTotal = Object.values(a.refused).reduce((s, n) => s + n, 0);
  const readings = Object.values(d.readings ?? {}).reduce((s, n) => s + n, 0);
  const logRows = (d.log ?? []).filter((t) => showLog ? `${t.key}|${t.symbol}` === showLog : false);
  const logTotal = logRows.reduce((s, t) => s + (t.pnl ?? 0), 0);

  return (
    <div className="min-w-0 overflow-hidden rounded-2xl border border-gray-200 bg-white dark:border-white/[0.05] dark:bg-white/[0.03]">
      <div className="px-5 pt-4">
        <h3 className="flex flex-wrap items-center gap-2 text-base font-semibold text-gray-800 dark:text-white/90">
          Forecast for the account <StoreBadge store="v2" />
          <button onClick={() => load(true)} disabled={busy}
            className="ml-auto rounded-lg border border-gray-300 px-3 py-1 text-theme-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-white/[0.05]">
            {busy ? "replaying…" : "REPLAY AGAIN"}
          </button>
        </h3>
        {/* provenance: what was replayed, at what stake, over which days */}
        <p className="text-theme-xs text-gray-500 dark:text-gray-400">
          every one of your {a.rows_deployed} switched-on rows, run together as one practice
          account · {a.signals.toLocaleString()} signals over {days} days
          ({fmtWhenMs(a.window.first_ms)} → {fmtWhenMs(a.window.last_ms)}) · ${a.base_margin} a trade
          at {a.leverage}x{a.sizing === "martingale" ? ", doubled after a loss (Martingale is on for demo)" : ", flat"} ·
          at most {a.slices_per_coin} rows on one coin at once · every exit settled by the minute ·
          cost per trade from {readings.toLocaleString()} real book readings in your own trade record — a
          signal with no reading nearby is refused, never guessed
        </p>
      </div>

      {/* the headline: what the account would have done */}
      <div className="mt-4 grid grid-cols-2 gap-3 px-5 sm:grid-cols-3 lg:grid-cols-6">
        <Tile label="trades taken" value={a.trades.toLocaleString()} sub={`${refusedTotal.toLocaleString()} refused`} />
        <Tile label="win rate" value={`${a.win_rate}%`} sub={`${a.wins} won · ${a.losses} lost`} />
        <Tile label={a.sizing === "martingale" ? "money, doubling on" : "money, flat"} value={money(a.pnl)} tone={a.pnl >= 0 ? "good" : "bad"}
              sub={d.flat ? `flat: ${money(d.flat.pnl)}` : ""} />
        <Tile label="worst losing run" value={money(a.worst_run.pnl)} tone="bad"
              sub={`${a.worst_run.trades} losses in a row${d.flat ? ` · flat ${money(d.flat.worst_run.pnl)}` : ""}`} />
        <Tile label="rows that traded" value={`${a.rows_traded} of ${a.rows_deployed}`}
              sub={`${a.rows_deployed - a.rows_traded} did not trade — see why below`} />
        <Tile label="both prices in one minute" value={a.unclear.toLocaleString()} sub="counted as losses" />
      </div>

      {/* refusals, by name, in plain words */}
      {refusedTotal > 0 && (
        <p className="mt-3 px-5 text-theme-xs text-gray-600 dark:text-gray-400">
          <span className="font-medium">refused, and why:</span>{" "}
          {Object.entries(a.refused).sort((x, y) => y[1] - x[1]).map(([k, n]) =>
            `${n.toLocaleString()} because ${REFUSAL_WORDS[k] ?? k}`).join(" · ")}
        </p>
      )}

      {/* the check against the real practice record */}
      {c && act && (
        <div className="mx-5 mt-4 rounded-xl border border-gray-200 p-4 dark:border-white/[0.08]">
          <p className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">
            Checked against your practice account
            <span className="ml-2 font-normal text-gray-500 dark:text-gray-400">
              {fmtWhenMs(c.window.first_ms)} → {fmtWhenMs(c.window.last_ms)}, each row from the day you switched it on
            </span>
          </p>
          <div className="mt-2 overflow-x-auto">
            <table className="text-theme-xs text-gray-700 dark:text-gray-300">
              <thead>
                <tr className="text-gray-500 dark:text-gray-400">
                  <th className="pr-4 text-start font-medium"></th>
                  <th className="pr-4 text-start font-medium">trades</th>
                  <th className="pr-4 text-start font-medium">won / lost</th>
                  <th className="pr-4 text-start font-medium">win rate</th>
                  <th className="pr-4 text-start font-medium">money at ${a.base_margin} flat</th>
                  <th className="pr-4 text-start font-medium">refused</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td className="pr-4 font-medium">this replay</td>
                  <td className="pr-4">{c.trades}</td>
                  <td className="pr-4">{c.wins} / {c.losses}</td>
                  <td className="pr-4">{c.win_rate}%</td>
                  <td className="pr-4">{money(c.pnl)}</td>
                  <td className="pr-4">{Object.values(c.refused).reduce((s, n) => s + n, 0).toLocaleString()}</td>
                </tr>
                <tr>
                  <td className="pr-4 font-medium">your practice account</td>
                  <td className="pr-4">{act.trades}</td>
                  <td className="pr-4">{act.wins} / {act.losses}</td>
                  <td className="pr-4">{act.win_rate}%</td>
                  <td className="pr-4">
                    {money(act.pnl_at_base)}
                    <span className="text-gray-500 dark:text-gray-400"> (booked {money(act.pnl)} at the stakes of the day, with the fee counted twice until Sep 23, 2026)</span>
                  </td>
                  <td className="pr-4">{Object.values(act.refused).reduce((s, n) => s + n, 0).toLocaleString()}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-theme-xs text-gray-500 dark:text-gray-400">
            The practice account's trades include rows you have since switched off; the replay runs only
            what is switched on today. Where the two lines differ, the replay is the one to doubt — it
            only knows the venue's book at the {readings.toLocaleString()} moments your record wrote down,
            and from today the runner writes every reading, so this check tightens on its own.
          </p>
        </div>
      )}

      {/* every row, every column */}
      <div className="mt-4 px-5 text-theme-xs text-gray-500 dark:text-gray-400">
        {a.rows_deployed} rows switched on · {a.rows_traded} traded in the replay · click a row for its trades
      </div>
      <div className="mt-2 w-full overflow-x-auto">
        <Table>
          <TableHeader className="border-y border-gray-100 dark:border-white/[0.05]">
            <TableRow>
              {head("id")}{head("coin")}{head("tf")}{head("signal")}{head("TP")}{head("SL")}
              {head("trades", "trades")}{head("wins", "wins")}{head("losses", "losses")}
              {head("win rate", "win_rate")}{head("profit $", "pnl")}{head("worst run $", "worst_run")}
              {head("signals", "signals")}{head("refused for cost", "cost_refused")}
            </TableRow>
          </TableHeader>
          <TableBody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
            {rows.map((r) => (
              <TableRow key={r.row} className="cursor-pointer hover:bg-gray-50 dark:hover:bg-white/[0.03]"
                        onClick={() => setShowLog(showLog === r.row ? null : r.row)}>
                <TableCell className="px-3 py-2 text-theme-xs font-mono text-gray-700 dark:text-gray-300">#{(r as ForecastRow & { id?: string }).id ?? ""}</TableCell>
                <TableCell className="px-3 py-2 text-theme-xs text-gray-700 dark:text-gray-300">{r.coin}</TableCell>
                <TableCell className="px-3 py-2 text-theme-xs text-gray-700 dark:text-gray-300">{r.tf}</TableCell>
                <TableCell className="px-3 py-2 text-theme-xs text-gray-700 dark:text-gray-300">{r.key}</TableCell>
                <TableCell className="px-3 py-2 text-theme-xs text-gray-700 dark:text-gray-300">{pct(r.tp * 100)}</TableCell>
                <TableCell className="px-3 py-2 text-theme-xs text-gray-700 dark:text-gray-300">{pct(r.sl * 100)}</TableCell>
                <TableCell className="px-3 py-2 text-theme-xs text-gray-700 dark:text-gray-300">{r.trades}</TableCell>
                <TableCell className="px-3 py-2 text-theme-xs text-success-600 dark:text-success-400">{r.wins}</TableCell>
                <TableCell className="px-3 py-2 text-theme-xs text-error-600 dark:text-error-400">{r.losses}</TableCell>
                <TableCell className="px-3 py-2 text-theme-xs text-gray-700 dark:text-gray-300">{r.win_rate}%</TableCell>
                <TableCell className={`px-3 py-2 text-theme-xs font-medium ${r.pnl >= 0 ? "text-success-600 dark:text-success-400" : "text-error-600 dark:text-error-400"}`}>{money(r.pnl)}</TableCell>
                <TableCell className="px-3 py-2 text-theme-xs text-gray-700 dark:text-gray-300">{money(r.worst_run)}</TableCell>
                <TableCell className="px-3 py-2 text-theme-xs text-gray-700 dark:text-gray-300">{r.signals}</TableCell>
                <TableCell className="px-3 py-2 text-theme-xs text-gray-700 dark:text-gray-300">{r.cost_refused}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {/* the trade-by-trade log of the clicked row, with its own total */}
      {showLog && (
        <div className="mx-5 mt-3 rounded-xl border border-gray-200 p-3 dark:border-white/[0.08]">
          <p className="text-theme-xs font-medium text-gray-800 dark:text-white/90">
            {showLog.replace("_USDT", "").replace("|", " on ")} — {logRows.length} trades,
            TOTAL PROFIT {money(logTotal)}
          </p>
          <div className="mt-2 max-h-72 overflow-auto">
            <table className="text-theme-xs text-gray-700 dark:text-gray-300">
              <thead><tr className="text-gray-500 dark:text-gray-400">
                <th className="pr-3 text-start font-medium">opened</th><th className="pr-3 text-start font-medium">side</th>
                <th className="pr-3 text-start font-medium">entry</th><th className="pr-3 text-start font-medium">closed</th>
                <th className="pr-3 text-start font-medium">how</th><th className="pr-3 text-start font-medium">cost</th>
                <th className="pr-3 text-start font-medium">stake $</th><th className="pr-3 text-start font-medium">profit $</th>
              </tr></thead>
              <tbody>
                {logRows.map((t, i) => (
                  <tr key={i}>
                    <td className="pr-3">{fmtWhenMs(t.entry_ms)}</td>
                    <td className="pr-3">{t.side === 1 ? "long" : "short"}</td>
                    <td className="pr-3">{t.entry}</td>
                    <td className="pr-3">{fmtWhenMs(t.exit_ms)}</td>
                    <td className="pr-3">{t.why === "TP" ? "won" : t.why === "SL" ? (t.unclear ? "lost (both prices in one minute)" : "lost") : t.why === "LIQ" ? "liquidated" : t.why}</td>
                    <td className="pr-3">{pct(t.cost * 100)}{t.cost_source === "saved" ? "*" : ""}</td>
                    <td className="pr-3">{t.margin}</td>
                    <td className={`pr-3 ${(t.pnl ?? 0) >= 0 ? "text-success-600 dark:text-success-400" : "text-error-600 dark:text-error-400"}`}>{money(t.pnl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-1 text-theme-xs text-gray-500 dark:text-gray-400">* cost from the saved reading — your record had no book reading near that minute</p>
        </div>
      )}

      {/* rows that never traded, and why */}
      {Object.keys(a.rows_refused).length > 0 && (
        <details className="mx-5 mt-3 text-theme-xs text-gray-600 dark:text-gray-400">
          <summary className="cursor-pointer font-medium">{Object.keys(a.rows_refused).length} rows did not trade — why</summary>
          <ul className="mt-1 list-disc pl-5">
            {Object.entries(a.rows_refused).map(([row, why]) => (
              <li key={row}>{row.replace("_USDT", "").replace("|", " on ")}: {why}</li>
            ))}
          </ul>
        </details>
      )}

      {/* what it does not model — named, never assumed away */}
      <details className="mx-5 mb-4 mt-3 text-theme-xs text-gray-600 dark:text-gray-400">
        <summary className="cursor-pointer font-medium">what this replay still cannot see</summary>
        <ul className="mt-1 list-disc pl-5">
          {a.assumptions.map((s, i) => <li key={i}>{s}</li>)}
        </ul>
      </details>
    </div>
  );
}

function Tile({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "good" | "bad" }) {
  const color = tone === "good" ? "text-success-600 dark:text-success-400"
    : tone === "bad" ? "text-error-600 dark:text-error-400" : "text-gray-800 dark:text-white/90";
  return (
    <div className="rounded-xl border border-gray-200 p-3 dark:border-white/[0.08]">
      <div className="text-theme-xs text-gray-500 dark:text-gray-400">{label}</div>
      <div className={`mt-1 text-lg font-semibold ${color}`}>{value}</div>
      {sub ? <div className="text-theme-xs text-gray-500 dark:text-gray-400">{sub}</div> : null}
    </div>
  );
}
