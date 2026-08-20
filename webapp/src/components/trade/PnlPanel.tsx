"use client";
/** Per-coin and per-day realized PnL. Every total here is summed from the
 * rows shown beside it, so the caption cannot disagree with the table. */
import { useEffect, useState } from "react";
import { DayStat, fmtMoney, tradeApi } from "@/lib/api";
import { Table, TableBody, TableCell, TableHeader, TableRow } from "@/components/ui/table";

type CoinStat = { pnl: number; trades: number; wins: number; losses: number };

export default function PnlPanel() {
  const [coins, setCoins] = useState<Record<string, CoinStat>>({});
  const [days, setDays] = useState<Record<string, DayStat>>({});
  const [dry, setDry] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    Promise.all([tradeApi.pnlByCoin(dry), tradeApi.pnlDaily(dry)])
      .then(([c, d]) => { setCoins(c.coins); setDays(d.days); setErr(""); })
      .catch((e) => setErr(String(e)));
  }, [dry]);

  const coinRows = Object.entries(coins).sort((a, b) => b[1].pnl - a[1].pnl);
  const dayRows = Object.entries(days).sort((a, b) => (a[0] < b[0] ? 1 : -1)).slice(0, 30);
  const coinTotal = coinRows.reduce((a, [, v]) => a + v.pnl, 0);
  const dayTotal = dayRows.reduce((a, [, v]) => a + v.pnl, 0);
  const trades = coinRows.reduce((a, [, v]) => a + v.trades, 0);
  const wins = coinRows.reduce((a, [, v]) => a + v.wins, 0);
  const losses = coinRows.reduce((a, [, v]) => a + v.losses, 0);

  return (
    <div className="grid gap-5 xl:grid-cols-2">
      <div className="overflow-hidden rounded-2xl border border-gray-200 bg-white dark:border-white/[0.05] dark:bg-white/[0.03]">
        <div className="flex items-center gap-3 px-5 pt-4">
          <div>
            <h3 className="text-base font-semibold text-gray-800 dark:text-white/90">Closed profit by coin</h3>
            <p className="text-theme-xs text-gray-500 dark:text-gray-400">
              {coinRows.length} coins · {fmtMoney(coinTotal)} total · {trades} closed trades · {wins}W / {losses}L
            </p>
          </div>
          <label className="ml-auto flex items-center gap-2 text-theme-xs text-gray-600 dark:text-gray-300">
            <input type="checkbox" checked={dry} onChange={(e) => setDry(e.target.checked)} className="h-4 w-4 accent-brand-500" />
            paper book
          </label>
        </div>
        {err && <p className="px-5 pt-2 text-theme-sm text-error-500">{err}</p>}
        <div className="max-h-72 max-w-full overflow-auto p-2">
          <Table>
            <TableHeader className="sticky top-0 bg-white dark:bg-gray-900">
              <TableRow>
                {["coin", "PROFIT $", "trades", "W", "L", "win %"].map((h) => (
                  <TableCell key={h} isHeader className="px-3 py-2 text-theme-xs font-medium text-gray-500 text-start dark:text-gray-400">{h}</TableCell>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
              {coinRows.map(([coin, v]) => (
                <TableRow key={coin}>
                  <TableCell className="px-3 py-2 text-theme-sm font-medium text-gray-800 dark:text-white/90">{coin.replace("_USDT", "")}</TableCell>
                  <TableCell className={`px-3 py-2 text-theme-sm font-semibold ${v.pnl >= 0 ? "text-success-600" : "text-error-500"}`}>{fmtMoney(v.pnl)}</TableCell>
                  <TableCell className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{v.trades}</TableCell>
                  <TableCell className="px-3 py-2 text-theme-sm text-success-600">{v.wins}</TableCell>
                  <TableCell className="px-3 py-2 text-theme-sm text-error-500">{v.losses}</TableCell>
                  <TableCell className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{v.trades ? ((v.wins / v.trades) * 100).toFixed(1) : "—"}</TableCell>
                </TableRow>
              ))}
              {!coinRows.length && <TableRow><TableCell className="px-3 py-4 text-theme-sm text-gray-500 dark:text-gray-400">No closed trades on this book yet.</TableCell></TableRow>}
            </TableBody>
          </Table>
        </div>
      </div>

      <div className="overflow-hidden rounded-2xl border border-gray-200 bg-white dark:border-white/[0.05] dark:bg-white/[0.03]">
        <h3 className="px-5 pt-4 text-base font-semibold text-gray-800 dark:text-white/90">Day by day</h3>
        <p className="px-5 text-theme-xs text-gray-500 dark:text-gray-400">
          latest {dayRows.length} days · {fmtMoney(dayTotal)} over that window ·{" "}
          {dayRows.reduce((a, [, v]) => a + v.wins, 0)}W /{" "}
          {dayRows.reduce((a, [, v]) => a + v.losses, 0)}L
        </p>
        <div className="max-h-72 max-w-full overflow-auto p-2">
          <Table>
            <TableBody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
              {dayRows.map(([day, v]) => (
                <TableRow key={day}>
                  <TableCell className="px-3 py-1.5 text-theme-sm text-gray-500 dark:text-gray-400">{day}</TableCell>
                  <TableCell className={`px-3 py-1.5 text-theme-sm font-medium ${v.pnl >= 0 ? "text-success-600" : "text-error-500"}`}>{fmtMoney(v.pnl)}</TableCell>
                  <TableCell className="px-3 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{v.wins}W / {v.losses}L</TableCell>
                  <TableCell className="px-3 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{v.coins.join(", ")}</TableCell>
                  <TableCell className="px-3 py-1.5">
                    <span className={`inline-block h-2 rounded-full ${v.pnl >= 0 ? "bg-success-500" : "bg-error-500"}`}
                      style={{ width: `${Math.min(100, Math.abs(v.pnl) * 3)}px` }} />
                  </TableCell>
                </TableRow>
              ))}
              {!dayRows.length && <TableRow><TableCell className="px-3 py-4 text-theme-sm text-gray-500 dark:text-gray-400">No closed days on this book yet.</TableCell></TableRow>}
            </TableBody>
          </Table>
        </div>
      </div>
    </div>
  );
}
