"use client";
/** Open positions, straight from the exchange — the source of truth. */
import { OpenPosition, PaperPosition, fmtMoney } from "@/lib/api";
import { Table, TableBody, TableCell, TableHeader, TableRow } from "@/components/ui/table";

export default function PositionsPanel({ real, paper }: { real: OpenPosition[]; paper: PaperPosition[] }) {
  return (
    <div className="overflow-hidden rounded-2xl border border-gray-200 bg-white dark:border-white/[0.05] dark:bg-white/[0.03]">
      <h3 className="px-5 pt-4 text-base font-semibold text-gray-800 dark:text-white/90">Open positions</h3>
      <p className="px-5 text-theme-xs text-gray-500 dark:text-gray-400">
        {real.length} real (exchange-confirmed) · {paper.length} paper (simulated)
      </p>
      <div className="max-w-full overflow-x-auto p-2">
        <Table>
          <TableHeader>
            <TableRow>
              {["book", "coin", "side", "entry", "margin $", "unrealized $"].map((h) => (
                <TableCell key={h} isHeader className="px-3 py-2 text-theme-xs font-medium text-gray-500 text-start dark:text-gray-400">{h}</TableCell>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
            {real.map((p, i) => (
              <TableRow key={`r${i}`}>
                <TableCell className="px-3 py-2 text-theme-xs font-semibold text-error-500">REAL</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm font-medium text-gray-800 dark:text-white/90">{(p.symbol || "").replace("_USDT", "")}</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{p.side}</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{p.entry}</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{p.margin.toFixed(2)}</TableCell>
                <TableCell className={`px-3 py-2 text-theme-sm font-semibold ${p.unrealized >= 0 ? "text-success-600" : "text-error-500"}`}>{fmtMoney(p.unrealized)}</TableCell>
              </TableRow>
            ))}
            {paper.map((p, i) => (
              <TableRow key={`p${i}`}>
                <TableCell className="px-3 py-2 text-theme-xs font-semibold text-gray-400">paper</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm font-medium text-gray-800 dark:text-white/90">{(p.symbol || "").replace("_USDT", "")}</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{p.side}</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{p.entry ?? "—"}</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{p.margin?.toFixed(2) ?? "—"}</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{p.strategy ?? ""}</TableCell>
              </TableRow>
            ))}
            {!real.length && !paper.length && (
              <TableRow><TableCell className="px-3 py-4 text-theme-sm text-gray-500 dark:text-gray-400">Flat — nothing open on either book.</TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
