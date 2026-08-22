"use client";
/** Open positions — all fourteen columns, and the two books kept APART.
 *
 * Each book gets its own bordered box with a coloured badge: two ruled grids
 * stacked read as one table, and "is this row real money or the simulator?"
 * is the one question this section must never leave ambiguous.
 *
 * The column set is a standing operator decision — trimmed to five twice
 * (Streamlit 2026-08-20, React 2026-08-21) and restored both times. `bracket`
 * is the one that matters most: blank means the stop is resting at the
 * exchange, anything else means real money is open with no protection.
 */
import { useEffect, useState } from "react";
import { fmtMoney, PositionRow, PositionsPayload, tradeApi } from "@/lib/api";
import Badge from "@/components/ui/badge/Badge";
import { Table, TableBody, TableCell, TableHeader, TableRow } from "@/components/ui/table";

const HEADS: [string, string][] = [
  ["contract", "13%"], ["unreal $", "6%"], ["to TP", "8%"], ["TP % ($)", "9%"],
  ["SL % ($)", "9%"], ["W", "3%"], ["L", "3%"], ["trd", "4%"], ["side", "6%"],
  ["opened", "10%"], ["held", "6%"], ["entry", "8%"], ["margin", "6%"],
  ["bracket", "9%"],
];

function Progress({ r }: { r: PositionRow }) {
  if (r.progress_pct == null) return <span className="text-gray-400">—</span>;
  const toTp = r.progress_to === "TP";
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-1">
      <span className="h-1.5 w-6 shrink-0 overflow-hidden rounded-full bg-gray-100 dark:bg-white/[0.08]">
        <span className={`block h-full rounded-full ${toTp ? "bg-success-500" : "bg-error-500"}`}
          style={{ width: `${r.progress_pct}%` }} />
      </span>
      <span className={`text-[10px] leading-tight ${toTp ? "text-success-600" : "text-error-500"}`}>
        {r.progress_pct}% {r.progress_to}
      </span>
    </div>
  );
}

const Barrier = ({ v, win }: { v: { pct: number; usd: number } | null; win: boolean }) =>
  v == null ? <span className="text-gray-400">—</span> : (
    <span className="inline-block leading-tight">
      {v.pct.toFixed(2)}{" "}
      <span className={win ? "text-success-600" : "text-error-500"}>({fmtMoney(v.usd)})</span>
    </span>
  );

export default function PositionsPanel({ onChanged }: { onChanged?: () => void }) {
  const [data, setData] = useState<PositionsPayload | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState("");

  const load = () => tradeApi.positions().then((d) => { setData(d); setErr(""); }).catch((e) => setErr(String(e)));
  useEffect(() => {
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, []);

  const closeOne = async (r: PositionRow) => {
    const worth = r.unrealized == null ? "" :
      `\n\nUnrealized ${fmtMoney(r.unrealized)} USDT becomes REAL the moment this fills.`;
    if (!confirm(`Close ${r.coin} at market now?\n\n${r.side} ${r.vol ?? "?"} contracts, entry ${r.entry}, ${r.margin ?? "?"} USDT margin at ${data?.leverage ?? 20}x.${worth}\n\nThere is no undo, and the strategy may re-enter on its next signal.`)) return;
    setBusy(r.symbol);
    try {
      const got = await tradeApi.closeOne(r.symbol);
      if (!got.closed) setErr(`${r.coin} did not close: ${got.why ?? "the exchange refused"}`);
      await load();
      onChanged?.();
    } catch (e) { setErr(String(e)); } finally { setBusy(""); }
  };

  const row = (r: PositionRow, book: "REAL" | "paper") => (
    <TableRow key={`${book}-${r.symbol}`}>
      <TableCell className="px-2 py-1.5 text-theme-xs">
        <span className="block font-medium text-gray-800 dark:text-white/90">{r.coin}</span>
        {/* the SAME id the strategy grid prints, so "which strategy is running
            here?" is answerable from this row alone — and it is the id to
            paste into a report's find-by-ID box */}
        {r.id ? (
          <button onClick={() => navigator.clipboard?.writeText(r.id)}
            title="copy this id"
            className="block font-mono text-[10px] font-semibold leading-tight text-brand-500 hover:underline">
            #{r.id}
          </button>
        ) : null}
        <span className="block text-[10px] leading-tight text-gray-400">{r.strategy}</span>
      </TableCell>
      <TableCell className={`px-2 py-1.5 text-theme-xs font-semibold ${(r.unrealized ?? 0) >= 0 ? "text-success-600" : "text-error-500"}`}>
        {r.unrealized == null ? "—" : fmtMoney(r.unrealized)}
      </TableCell>
      <TableCell className="px-2 py-1.5"><Progress r={r} /></TableCell>
      <TableCell className="px-2 py-1.5 text-theme-xs text-gray-600 dark:text-gray-300"><Barrier v={r.tp_value} win /></TableCell>
      <TableCell className="px-2 py-1.5 text-theme-xs text-gray-600 dark:text-gray-300"><Barrier v={r.sl_value} win={false} /></TableCell>
      <TableCell className="px-2 py-1.5 text-theme-xs text-success-600">{r.wins}</TableCell>
      <TableCell className="px-2 py-1.5 text-theme-xs text-error-500">{r.losses}</TableCell>
      <TableCell className="px-2 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{r.trades}</TableCell>
      <TableCell className={`px-2 py-1.5 text-theme-xs font-medium ${r.side === "LONG" ? "text-success-600" : "text-error-500"}`}>{r.side}</TableCell>
      <TableCell className="px-2 py-1.5 text-[10px] leading-tight text-gray-500 dark:text-gray-400">
        {/* two lines: nowrap forced this column wider than its share and the
            stamp ran under "held" */}
        {(() => {
          const m = r.opened.match(/^(.*\d{4})\s+(.*)$/);   // "Aug 20, 2026" + "11:30PM"
          return m ? <><span className="block">{m[1]}</span><span className="block">{m[2]}</span></> : r.opened;
        })()}
      </TableCell>
      <TableCell className="px-2 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{r.held}</TableCell>
      <TableCell className="px-2 py-1.5 text-theme-xs text-gray-700 dark:text-gray-300">{r.entry ?? "—"}</TableCell>
      <TableCell className="px-2 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{r.margin ?? "—"}</TableCell>
      <TableCell className="px-2 py-1.5">
        <div className="flex min-w-0 flex-wrap items-center gap-1">
          {r.bracket
            ? <Badge size="sm" color="error">{r.bracket}</Badge>
            : <span className="text-theme-xs text-gray-400">—</span>}
          {book === "REAL" && (
            <button onClick={() => closeOne(r)} disabled={busy === r.symbol}
              className="rounded-lg border border-error-200 px-2 py-0.5 text-theme-xs font-medium text-error-500 hover:bg-error-50 disabled:opacity-50 dark:border-error-500/30">
              {busy === r.symbol ? "closing…" : "close"}
            </button>
          )}
        </div>
      </TableCell>
    </TableRow>
  );

  const Book = ({ label, tone, rows, empty, book }: {
    label: string; tone: "real" | "paper"; rows: PositionRow[]; empty: string;
    book: "REAL" | "paper";
  }) => (
    <div className={`overflow-hidden rounded-xl border ${tone === "real"
      ? "border-error-200 dark:border-error-500/30" : "border-gray-200 dark:border-white/[0.08]"}`}>
      <div className={`flex items-center gap-2 px-4 py-2 text-theme-xs font-semibold tracking-wide ${
        tone === "real" ? "bg-error-50 text-error-600 dark:bg-error-500/10"
                        : "bg-gray-50 text-gray-500 dark:bg-white/[0.04] dark:text-gray-400"}`}>
        {label}<span className="font-normal">· {rows.length} open</span>
      </div>
      {rows.length ? (
        <div className="w-full">
          <Table fixed>
            <TableHeader className="border-b border-gray-100 dark:border-white/[0.05]">
              <TableRow>
                {HEADS.map(([h, w]) => (
                  <TableCell key={h} isHeader style={{ width: w }}
                    className="px-2 py-1.5 text-theme-xs font-medium text-gray-500 text-start dark:text-gray-400">{h}</TableCell>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
              {rows.map((r) => row(r, book))}
            </TableBody>
          </Table>
        </div>
      ) : (
        <p className="px-4 py-3 text-theme-sm text-gray-500 dark:text-gray-400">{empty}</p>
      )}
    </div>
  );

  const real = data?.real ?? [];
  const paper = data?.paper ?? [];

  return (
    <div className="min-w-0 overflow-hidden rounded-2xl border border-gray-200 bg-white dark:border-white/[0.05] dark:bg-white/[0.03]">
      <div className="px-5 pt-4">
        <h3 className="text-base font-semibold text-gray-800 dark:text-white/90">Positions</h3>
        <p className="text-theme-xs text-gray-500 dark:text-gray-400">
          {real.length} real · {paper.length} paper · {data?.leverage ?? 20}x isolated ·
          dollar figures are net of the round-trip fee
        </p>
      </div>
      {!!data?.unprotected.length && (
        <p className="mx-5 mt-2 rounded-lg bg-error-50 px-3 py-2 text-theme-sm font-medium text-error-600 dark:bg-error-500/10">
          {data.unprotected.join(", ")} {data.unprotected.length === 1 ? "has" : "have"} NO STOP resting at the exchange — real money is open unprotected.
        </p>
      )}
      {err && <p className="px-5 pt-2 text-theme-sm text-error-500">{err}</p>}
      <div className="flex flex-col gap-4 p-4">
        <Book label="REAL — MONEY AT RISK" tone="real" book="REAL" rows={real}
          empty="none — no real money at risk" />
        <Book label="PAPER — DEMO, NOT REAL MONEY" tone="paper" book="paper" rows={paper}
          empty="none — no simulated position open" />
      </div>
    </div>
  );
}
