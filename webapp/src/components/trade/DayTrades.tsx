"use client";
/** THE TRADES OF ONE CALENDAR DAY (operator, Nov 12, 2026: *"in auto trade, if i
 * click a date in calendar show me the trades made on that day in table"*).
 *
 * Opened by a click on a box of the Day by day calendar. The day is a LOCAL
 * "YYYY-MM-DD", the very key `auto_trader.daily_pnl` files the box under, and
 * it goes to the SERVER (`/api/trade/history?day=`), which cuts it from every
 * closed trade — never a `.filter()` here over a page the server already cut
 * (CLAUDE.md, filter where the data is). The book is the calendar's own, so a
 * box and its table count the same exits; the line above the table prints
 * the table's own totals, summed by the server from the rows it matched.
 */
import { useRef, useState } from "react";
import { useLiveRefresh } from "@/lib/live";
import { fmtMoney, HistoryPayload } from "@/lib/api";
import { useRoomApis } from "@/lib/room";
import PageButtons from "@/components/common/PageButtons";
import CopyableId from "./CopyableId";
import { Table, TableBody, TableCell, TableHeader, TableRow } from "@/components/ui/table";

const PER_PAGE = 10;
const HEADS = ["closed", "opened", "held", "coin", "side", "strategy", "closed by", "PROFIT $"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export default function DayTrades({ day, dry }: { day: string; dry: boolean }) {
  const { tradeApi } = useRoomApis();
  const [page, setPage] = useState(1);
  // the answer is kept with what it was asked for and shown only while that is
  // still what is on screen (PnlPanel's rule): a late answer for the day or
  // book just left must never print under the new one's name
  const [got, setGot] = useState<{ key: string; data: HistoryPayload } | null>(null);
  const [err, setErr] = useState("");
  const want = `${day}|${dry}|${page}`;
  const wantNow = useRef(want);
  wantNow.current = want;
  // a new day or book starts on page 1: the caller keys this component by both

  useLiveRefresh(() => {
    const asked = `${day}|${dry}|${page}`;
    tradeApi.history(dry, page, PER_PAGE, "", day)
      .then((r) => { if (asked === wantNow.current) { setGot({ key: asked, data: r }); setErr(""); } })
      .catch((e) => setErr(String(e)));
  }, 5_000, [day, dry, page]);

  const d = got && got.key === want ? got.data : null;
  const t = d?.totals;
  const label = `${MONTHS[Number(day.slice(5, 7)) - 1]} ${day.slice(8, 10)}, ${day.slice(0, 4)}`;
  const book = dry ? "practice" : "real-money";

  return (
    <div className="mt-3 rounded-xl border border-gray-200 dark:border-white/[0.07]" data-testid="day-trades">
      <p className="px-3 pt-2 text-theme-xs text-gray-600 dark:text-gray-300">
        <b>{label}</b> · {book} account ·{" "}
        {d
          ? (t && t.trades
              ? <>{t.trades} trade{t.trades === 1 ? "" : "s"}, {t.wins}W / {t.losses}L ·{" "}
                  <span className="font-semibold">TOTAL PROFIT </span>
                  <span className={`font-semibold ${t.profit >= 0 ? "text-success-600" : "text-error-500"}`}>{fmtMoney(t.profit)}</span></>
              : "no closed trade")
          : err ? <span className="text-error-500">could not read: {err}</span> : "reading the trades…"}
      </p>

      {/* phone: cards, as Trade history does — a table of eight columns is 48px each */}
      <div className="flex flex-col gap-2 p-3 md:hidden">
        {(d?.rows ?? []).map((r, i) => (
          <div key={`m-${r.ts}-${i}`} className="rounded-lg border border-gray-200 p-2 dark:border-white/[0.07]">
            <div className="flex items-start justify-between gap-2">
              <span className="text-theme-sm font-medium text-gray-800 dark:text-white/90">
                {r.coin} <span className={`text-theme-xs ${r.side === "LONG" ? "text-success-600" : "text-error-500"}`}>{r.side}</span>
                {r.why ? <span className="text-theme-xs text-gray-500 dark:text-gray-400"> · {r.why}</span> : null}
              </span>
              <span className={`shrink-0 text-theme-sm font-semibold ${r.profit >= 0 ? "text-success-600" : "text-error-500"}`}>{fmtMoney(r.profit)}</span>
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 text-theme-xs text-gray-500 dark:text-gray-400">
              {r.strategy_id ? <CopyableId id={r.strategy_id} /> : null}
              <span className="min-w-0 break-words">{r.strategy}</span>
            </div>
            <div className="mt-1 flex flex-wrap gap-x-3 text-theme-xs text-gray-500 dark:text-gray-400">
              <span>opened {r.opened ?? "—"}</span><span>closed {r.when}</span>{r.held ? <span>held {r.held}</span> : null}
            </div>
          </div>
        ))}
      </div>

      <div className="hidden w-full md:block">
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
                <TableCell className="px-2 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{r.when}</TableCell>
                <TableCell className="px-2 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{r.opened ?? "—"}</TableCell>
                <TableCell className="px-2 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{r.held ?? "—"}</TableCell>
                <TableCell className="px-2 py-1.5 text-theme-xs font-medium text-gray-800 dark:text-white/90">{r.coin}</TableCell>
                <TableCell className={`px-2 py-1.5 text-theme-xs ${r.side === "LONG" ? "text-success-600" : "text-error-500"}`}>{r.side}</TableCell>
                <TableCell className="break-all px-2 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">
                  {r.strategy_id ? <CopyableId id={r.strategy_id} /> : null}
                  <span className="block leading-tight">{r.strategy}</span>
                </TableCell>
                <TableCell className="px-2 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{r.why}</TableCell>
                <TableCell className={`px-2 py-1.5 text-theme-xs font-semibold ${r.profit >= 0 ? "text-success-600" : "text-error-500"}`}>{fmtMoney(r.profit)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      {d && !d.rows.length && (
        <p className="px-3 pb-3 text-theme-sm text-gray-500 dark:text-gray-400">
          No closed trade on the {book} account on {label}, out of the {d.examined ?? 0} it has closed in all.
        </p>
      )}
      <div className="px-3 pb-3">
        {d && <PageButtons cur={d.page} pages={d.pages} goto={setPage} what="day trades" />}
      </div>
    </div>
  );
}
