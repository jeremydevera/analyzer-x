"use client";
/** Open positions, all fourteen columns.
 *
 * The column set is a standing operator decision — they were trimmed to five
 * twice (Streamlit 2026-08-20, React 2026-08-21) and restored both times. The
 * one that matters most is `bracket`: blank means the stop is resting at the
 * exchange, and anything else means real money is open with no protection.
 */
import { useEffect, useState } from "react";
import { fmtMoney, PositionRow, PositionsPayload, tradeApi } from "@/lib/api";
import Badge from "@/components/ui/badge/Badge";
import { Table, TableBody, TableCell, TableHeader, TableRow } from "@/components/ui/table";

const HEADS = ["contract", "unreal $", "to TP", "TP % ($)", "SL % ($)", "W", "L",
  "trd", "side", "opened", "held", "entry", "margin", "bracket"];

function Progress({ r }: { r: PositionRow }) {
  if (r.progress_pct == null) return <span className="text-gray-400">—</span>;
  const toTp = r.progress_to === "TP";
  return (
    <div className="flex items-center gap-2">
      <span className="h-1.5 w-16 overflow-hidden rounded-full bg-gray-100 dark:bg-white/[0.08]">
        <span className={`block h-full rounded-full ${toTp ? "bg-success-500" : "bg-error-500"}`}
          style={{ width: `${r.progress_pct}%` }} />
      </span>
      <span className={`text-theme-xs ${toTp ? "text-success-600" : "text-error-500"}`}>
        {r.progress_pct}% {r.progress_to}
      </span>
    </div>
  );
}

const Barrier = ({ v, win }: { v: { pct: number; usd: number } | null; win: boolean }) =>
  v == null ? <span className="text-gray-400">—</span> : (
    <span className="whitespace-nowrap">
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

  const rows = (list: PositionRow[], book: "REAL" | "paper") =>
    list.map((r) => (
      <TableRow key={`${book}-${r.symbol}`}>
        <TableCell className="px-3 py-2 text-theme-sm">
          <span className={`mr-1.5 text-theme-xs font-semibold ${book === "REAL" ? "text-error-500" : "text-gray-400"}`}>{book}</span>
          <span className="font-medium text-gray-800 dark:text-white/90">{r.coin}</span>
          <span className="ml-1.5 text-theme-xs text-gray-400">{r.strategy}</span>
        </TableCell>
        <TableCell className={`px-3 py-2 text-theme-sm font-semibold ${(r.unrealized ?? 0) >= 0 ? "text-success-600" : "text-error-500"}`}>
          {r.unrealized == null ? "—" : fmtMoney(r.unrealized)}
        </TableCell>
        <TableCell className="px-3 py-2"><Progress r={r} /></TableCell>
        <TableCell className="px-3 py-2 text-theme-xs text-gray-600 dark:text-gray-300"><Barrier v={r.tp_value} win /></TableCell>
        <TableCell className="px-3 py-2 text-theme-xs text-gray-600 dark:text-gray-300"><Barrier v={r.sl_value} win={false} /></TableCell>
        <TableCell className="px-3 py-2 text-theme-xs text-success-600">{r.wins}</TableCell>
        <TableCell className="px-3 py-2 text-theme-xs text-error-500">{r.losses}</TableCell>
        <TableCell className="px-3 py-2 text-theme-xs text-gray-500 dark:text-gray-400">{r.trades}</TableCell>
        <TableCell className={`px-3 py-2 text-theme-xs font-medium ${r.side === "LONG" ? "text-success-600" : "text-error-500"}`}>{r.side}</TableCell>
        <TableCell className="px-3 py-2 whitespace-nowrap text-theme-xs text-gray-500 dark:text-gray-400">{r.opened}</TableCell>
        <TableCell className="px-3 py-2 text-theme-xs text-gray-500 dark:text-gray-400">{r.held}</TableCell>
        <TableCell className="px-3 py-2 text-theme-xs text-gray-700 dark:text-gray-300">{r.entry ?? "—"}</TableCell>
        <TableCell className="px-3 py-2 text-theme-xs text-gray-500 dark:text-gray-400">{r.margin ?? "—"}</TableCell>
        <TableCell className="px-3 py-2">
          <div className="flex items-center gap-2">
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
    ));

  const real = data?.real ?? [];
  const paper = data?.paper ?? [];

  return (
    <div className="overflow-hidden rounded-2xl border border-gray-200 bg-white dark:border-white/[0.05] dark:bg-white/[0.03]">
      <div className="px-5 pt-4">
        <h3 className="text-base font-semibold text-gray-800 dark:text-white/90">Open positions</h3>
        <p className="text-theme-xs text-gray-500 dark:text-gray-400">
          {real.length} real (exchange-confirmed) · {paper.length} paper (simulated) ·{" "}
          {data?.leverage ?? 20}x leverage · dollar figures are net of the round-trip fee
        </p>
      </div>
      {!!data?.unprotected.length && (
        <p className="mx-5 mt-2 rounded-lg bg-error-50 px-3 py-2 text-theme-sm font-medium text-error-600 dark:bg-error-500/10">
          {data.unprotected.join(", ")} {data.unprotected.length === 1 ? "has" : "have"} NO STOP resting at the exchange — real money is open unprotected.
        </p>
      )}
      {err && <p className="px-5 pt-2 text-theme-sm text-error-500">{err}</p>}
      <div className="max-w-full overflow-x-auto p-2">
        <Table>
          <TableHeader className="border-b border-gray-100 dark:border-white/[0.05]">
            <TableRow>
              {HEADS.map((h) => (
                <TableCell key={h} isHeader className="px-3 py-2 text-theme-xs font-medium text-gray-500 text-start dark:text-gray-400">{h}</TableCell>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
            {rows(real, "REAL")}
            {rows(paper, "paper")}
            {!real.length && !paper.length && (
              <TableRow><TableCell className="px-3 py-4 text-theme-sm text-gray-500 dark:text-gray-400">
                Flat — nothing open on either book.
              </TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
