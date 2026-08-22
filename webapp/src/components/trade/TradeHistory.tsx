"use client";
/** Every CLOSED trade, LIVE and DEMO on their own tabs.
 *
 * Five rows a page, numbered — a wall of 200 rows hides a trade as
 * effectively as a net figure does. The running total is computed over the
 * whole book, so page 3's "running $" is the real one, not the page's.
 */
import { useEffect, useState } from "react";
import { fmtMoney, HistoryPayload, tradeApi } from "@/lib/api";
import { Table, TableBody, TableCell, TableHeader, TableRow } from "@/components/ui/table";

// id and opened lead the row: the operator asked to be able to name a
// trade and see when it started (2026-08-22).
const HEADS = ["id", "opened", "closed", "held", "coin", "side", "strategy",
               "closed by", "PROFIT $", "running $"];

function pageNumbers(page: number, pages: number): number[] {
  const span = 7;
  let a = Math.max(1, page - Math.floor(span / 2));
  const b = Math.min(pages, a + span - 1);
  a = Math.max(1, b - span + 1);
  return Array.from({ length: b - a + 1 }, (_, i) => a + i);
}

export default function TradeHistory() {
  const [dry, setDry] = useState(false);
  const [page, setPage] = useState(1);
  const [d, setD] = useState<HistoryPayload | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    tradeApi.history(dry, page, 5).then((r) => { setD(r); setErr(""); }).catch((e) => setErr(String(e)));
  }, [dry, page]);

  useEffect(() => { setPage(1); }, [dry]);

  const t = d?.totals;
  return (
    <div className="min-w-0 overflow-hidden rounded-2xl border border-gray-200 bg-white dark:border-white/[0.05] dark:bg-white/[0.03]">
      <div className="flex flex-wrap items-center gap-3 px-5 pt-4">
        <div>
          <h3 className="text-base font-semibold text-gray-800 dark:text-white/90">Trade history</h3>
          <p className="text-theme-xs text-gray-500 dark:text-gray-400">
            every closed trade{d ? ` · ${d.total} on this book` : ""}
            {t && t.trades ? ` · ${t.wins}W / ${t.losses}L · ${fmtMoney(t.profit)} total` : ""}
          </p>
        </div>
        <div className="ml-auto flex gap-1 rounded-lg bg-gray-100 p-1 dark:bg-white/[0.06]">
          {([[false, "LIVE — real money"], [true, "DEMO — simulated"]] as const).map(([v, lab]) => (
            <button key={String(v)} onClick={() => setDry(v)}
              className={`rounded-md px-3 py-1 text-theme-xs font-medium transition ${dry === v
                ? (v ? "bg-white text-gray-800 shadow-theme-xs dark:bg-gray-800 dark:text-white/90"
                     : "bg-error-500 text-white")
                : "text-gray-500 dark:text-gray-400"}`}>
              {lab}
            </button>
          ))}
        </div>
      </div>
      {err && <p className="px-5 pt-2 text-theme-sm text-error-500">{err}</p>}

      <div className="w-full">
        <Table fixed>
          <TableHeader className="border-b border-gray-100 dark:border-white/[0.05]">
            <TableRow>
              {HEADS.map((h) => (
                <TableCell key={h} isHeader className="px-2 py-1.5 text-theme-xs font-medium text-gray-500 text-start dark:text-gray-400">{h}</TableCell>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
            {(d?.rows ?? []).map((r, i) => (
              <TableRow key={`${r.ts}-${i}`}>
                <TableCell className="whitespace-nowrap px-2 py-1.5 font-mono text-theme-xs text-gray-800 dark:text-white/90">{r.id ?? "—"}</TableCell>
                <TableCell className="whitespace-nowrap px-2 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{r.opened ?? "—"}</TableCell>
                <TableCell className="whitespace-nowrap px-3 py-2 text-theme-xs text-gray-500 dark:text-gray-400">{r.when}</TableCell>
                <TableCell className="whitespace-nowrap px-2 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{r.held ?? "—"}</TableCell>
                <TableCell className="px-2 py-1.5 text-theme-xs font-medium text-gray-800 dark:text-white/90">{r.coin}</TableCell>
                <TableCell className={`px-2 py-1.5 text-theme-xs ${r.side === "LONG" ? "text-success-600" : "text-error-500"}`}>{r.side}</TableCell>
                <TableCell className="px-2 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{r.strategy}</TableCell>
                <TableCell className="px-2 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{r.why}</TableCell>
                <TableCell className={`px-2 py-1.5 text-theme-xs font-semibold ${r.profit >= 0 ? "text-success-600" : "text-error-500"}`}>{fmtMoney(r.profit)}</TableCell>
                <TableCell className={`px-2 py-1.5 text-theme-xs ${r.running >= 0 ? "text-success-600" : "text-error-500"}`}>{fmtMoney(r.running)}</TableCell>
              </TableRow>
            ))}
            {d && !d.rows.length && (
              <TableRow><TableCell className="px-3 py-4 text-theme-sm text-gray-500 dark:text-gray-400">
                No closed trades on the {dry ? "demo" : "live"} book yet.
              </TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      {!!d && d.pages > 1 && (
        <div className="flex flex-wrap items-center gap-1 px-5 py-3">
          <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={d.page <= 1}
            className="rounded-lg border border-gray-200 px-2 py-1 text-theme-xs text-gray-600 disabled:opacity-40 dark:border-gray-700 dark:text-gray-300">
            newer
          </button>
          {pageNumbers(d.page, d.pages).map((n) => (
            <button key={n} onClick={() => setPage(n)}
              className={`rounded-lg px-2.5 py-1 text-theme-xs ${n === d.page
                ? "bg-brand-500 font-semibold text-white"
                : "border border-gray-200 text-gray-600 dark:border-gray-700 dark:text-gray-300"}`}>
              {n}
            </button>
          ))}
          <button onClick={() => setPage((p) => Math.min(d.pages, p + 1))} disabled={d.page >= d.pages}
            className="rounded-lg border border-gray-200 px-2 py-1 text-theme-xs text-gray-600 disabled:opacity-40 dark:border-gray-700 dark:text-gray-300">
            older
          </button>
          <span className="ml-2 text-theme-xs text-gray-500 dark:text-gray-400">
            page {d.page} of {d.pages} · 5 per page
          </span>
        </div>
      )}
    </div>
  );
}
