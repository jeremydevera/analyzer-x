"use client";
/** Deployment history and the trade ledger — both from this Mac's files. */
import { useEffect, useState } from "react";
import { api, DeploymentRow, fmtMoney, LedgerRow } from "@/lib/api";
import {
  Table, TableBody, TableCell, TableHeader, TableRow,
} from "@/components/ui/table";

const ts = (v: number) => new Date(v * 1000).toISOString().slice(0, 16).replace("T", " ");
/** Held time, from the seconds the ledger stores. */
const held = (s?: number | null) =>
  s == null ? "—" : s >= 86400 ? `${(s / 86400).toFixed(1)}d`
    : s >= 3600 ? `${Math.floor(s / 3600)}h ${Math.round((s % 3600) / 60)}m`
      : `${Math.max(1, Math.round(s / 60))}m`;

export default function HistoryPanel() {
  const [deps, setDeps] = useState<DeploymentRow[]>([]);
  const [ledger, setLedger] = useState<LedgerRow[]>([]);
  const [total, setTotal] = useState(0);

  useEffect(() => {
    api.deployments().then((d) => setDeps(d.rows)).catch(() => {});
    api.ledger(200).then((d) => { setLedger(d.rows); setTotal(d.total); }).catch(() => {});
  }, []);

  const trades = ledger.filter((r) => r.action === "enter" || r.action === "exit");

  return (
    <div className="grid gap-5 xl:grid-cols-2">
      <div className="overflow-hidden rounded-2xl border border-gray-200 bg-white dark:border-white/[0.05] dark:bg-white/[0.03]">
        <h3 className="px-5 pt-4 text-base font-semibold text-gray-800 dark:text-white/90">
          Deployment history
        </h3>
        <p className="px-5 text-theme-xs text-gray-500 dark:text-gray-400">what was live, when — {deps.length} changes recorded</p>
        <div className="max-h-72 max-w-full overflow-auto p-2">
          <Table>
            <TableBody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
              {deps.map((d, i) => (
                <TableRow key={i}>
                  <TableCell className="px-3 py-2 text-theme-xs text-gray-500 dark:text-gray-400">{ts(d.changed_at)}</TableCell>
                  <TableCell className="px-3 py-2 text-theme-sm font-medium text-gray-800 dark:text-white/90">{(d.symbol || "").replace("_USDT", "")}</TableCell>
                  <TableCell className="px-3 py-2 text-theme-xs text-gray-500 dark:text-gray-400">{d.action}</TableCell>
                  <TableCell className="px-3 py-2 text-theme-xs text-gray-500 dark:text-gray-400">{d.signal ?? d.strategy_key} {d.sl != null && `SL ${d.sl}/TP ${d.tp}`}</TableCell>
                  <TableCell className="px-3 py-2 text-theme-xs text-gray-500 dark:text-gray-400">{d.books ?? ""}</TableCell>
                </TableRow>
              ))}
              {!deps.length && (
                <TableRow><TableCell className="px-3 py-4 text-theme-sm text-gray-500 dark:text-gray-400">No changes recorded yet.</TableCell></TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </div>

      <div className="overflow-hidden rounded-2xl border border-gray-200 bg-white dark:border-white/[0.05] dark:bg-white/[0.03]">
        <h3 className="px-5 pt-4 text-base font-semibold text-gray-800 dark:text-white/90">
          Trade ledger
        </h3>
        <p className="px-5 text-theme-xs text-gray-500 dark:text-gray-400">
          {total.toLocaleString()} lines on this Mac — showing the latest entries/exits
        </p>
        <div className="max-h-72 max-w-full overflow-auto p-2">
          <Table>
            <TableHeader className="sticky top-0 bg-white dark:bg-gray-900">
              <TableRow>
                {["id", "opened", "when", "held", "coin", "action", "side", "pnl $", "closed by", "book"].map((h) => (
                  <TableCell key={h} isHeader className="px-3 py-2 text-theme-xs font-medium text-gray-500 text-start dark:text-gray-400">{h}</TableCell>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
              {trades.map((r, i) => (
                <TableRow key={i}>
                  <TableCell className="px-3 py-1.5 font-mono text-theme-xs text-gray-800 dark:text-white/90">{r.trade_id ?? "—"}</TableCell>
                  <TableCell className="px-3 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{r.opened_at ? ts(r.opened_at) : "—"}</TableCell>
                  <TableCell className="px-3 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{ts(r.ts)}</TableCell>
                  <TableCell className="px-3 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{held(r.held_s)}</TableCell>
                  <TableCell className="px-3 py-1.5 text-theme-sm font-medium text-gray-800 dark:text-white/90">{(r.symbol || "").replace("_USDT", "")}</TableCell>
                  <TableCell className="px-3 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{r.action}</TableCell>
                  <TableCell className="px-3 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{r.side ?? "—"}</TableCell>
                  <TableCell className={`px-3 py-1.5 text-theme-xs font-medium ${((r.pnl_est ?? r.pnl) ?? 0) >= 0 ? "text-success-600" : "text-error-500"}`}>{(r.pnl_est ?? r.pnl) != null ? fmtMoney((r.pnl_est ?? r.pnl) as number) : "—"}</TableCell>
                  <TableCell className="px-3 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{r.why ?? "—"}</TableCell>
                  <TableCell className="px-3 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">
                    {r.dry_run === false ? "REAL" : r.dry_run === true ? "paper" : "unknown"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </div>
    </div>
  );
}
