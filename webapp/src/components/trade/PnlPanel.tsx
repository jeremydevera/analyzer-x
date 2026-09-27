"use client";
/** Per-coin and per-day realized PnL. Every total here is summed from the
 * rows shown beside it, so the caption cannot disagree with the table. */
import { useEffect, useRef, useState } from "react";
import { markReady } from "@/lib/loading";
import { useLiveRefresh } from "@/lib/live";
import PanelStatus from "./PanelStatus";
import { DayStat, fmtMoney, tradeApi } from "@/lib/api";
import { Table, TableBody, TableCell, TableHeader, TableRow } from "@/components/ui/table";

type CoinStat = { pnl: number; trades: number; wins: number; losses: number };

export default function PnlPanel() {
  const [coins, setCoins] = useState<Record<string, CoinStat>>({});
  const [days, setDays] = useState<Record<string, DayStat>>({});
  const [dry, setDry] = useState(false);
  // WHICH BOOK THE NUMBERS ON SCREEN BELONG TO (null = none yet). Both reads
  // walk the whole ledger, 1.2-1.8 s measured, and the operator: *"when i
  // switch to real money its loading lag, can you make loading animation
  // before showing result"* (Sep 27, 2026). While `shown !== dry` the panel
  // shows a spinner, never the other book's figures under this book's name.
  const [shown, setShown] = useState<boolean | null>(null);
  const [err, setErr] = useState("");
  // an empty profit book is real data — "has it EVER loaded" is its own flag,
  // because days starts as {} and `!== null` would call it loaded at birth
  const got = useRef(false);
  // OPEN ON THE BOOK THAT HAS TRADES (operator, Sep 27, 2026: *"i cannot
  // see day by day pnl"*). The page opened on the real-money account, which
  // has 0 closed trades while every strategy is practice-only, so every box
  // of the new calendar was blank. Until the operator picks a book, an empty
  // real-money answer moves the panel to the practice account — and the
  // caption says which one it is showing.
  const picked = useRef(false);
  const pick = (v: boolean) => { picked.current = true; setDry(v); };

  // EVERY 5 SECONDS, and again the moment the tab is looked at. This loaded
  // ONCE and re-fetched only after a failure, so today's profit stopped
  // moving the second the page finished loading (operator, Sep 10, 2026:
  // *"i want the ui realtime"*). A failed fetch is now just the next tick's
  // job, which keeps the self-healing the retry gave (Sep 09, 2026).
  // THE ANSWER MUST BE FOR THE BOOK THE BOX SAYS. Both reads walk the whole
  // ledger (~1.2 s), so an answer for the book just switched AWAY from can
  // land after the new one and paint real-money days under "practice
  // account" until the next tick. A late answer for the other book is dropped.
  const dryNow = useRef(dry);
  useEffect(() => { dryNow.current = dry; }, [dry]);
  useLiveRefresh(() => {
    const asked = dry;
    Promise.all([tradeApi.pnlByCoin(dry), tradeApi.pnlDaily(dry)])
      .then(([c, d]) => {
        if (asked !== dryNow.current) return;
        if (!asked && !picked.current && !Object.keys(d.days).length) { setDry(true); return; }
        setCoins(c.coins); setDays(d.days); setShown(asked); setErr("");
        got.current = true; markReady("profit");
      })
      .catch((e) => setErr(String(e)));
  }, 5_000, [dry]);

  const loading = shown !== dry;
  const coinRows = Object.entries(loading ? {} : coins).sort((a, b) => b[1].pnl - a[1].pnl);
  const coinTotal = coinRows.reduce((a, [, v]) => a + v.pnl, 0);
  const trades = coinRows.reduce((a, [, v]) => a + v.trades, 0);
  const wins = coinRows.reduce((a, [, v]) => a + v.wins, 0);
  const losses = coinRows.reduce((a, [, v]) => a + v.losses, 0);

  return (
    <div className="grid min-w-0 gap-5 xl:grid-cols-2">
      <div className="min-w-0 overflow-hidden rounded-2xl border border-gray-200 bg-white dark:border-white/[0.05] dark:bg-white/[0.03]">
        <div className="flex items-center gap-3 px-5 pt-4">
          <div>
            <h3 className="text-base font-semibold text-gray-800 dark:text-white/90">Closed profit by coin</h3>
            <p className="text-theme-xs text-gray-500 dark:text-gray-400">
              {loading ? <Loading what={dry ? "practice account" : "real-money account"} />
                : <>{coinRows.length} coins · {fmtMoney(coinTotal)} total · {trades} closed trades · {wins}W / {losses}L</>}
            </p>
          </div>
          <label className="ml-auto flex items-center gap-2 text-theme-xs text-gray-600 dark:text-gray-300">
            <input type="checkbox" checked={dry} onChange={(e) => pick(e.target.checked)} className="h-4 w-4 accent-brand-500" />
            paper book
          </label>
        </div>
        <PanelStatus err={err} loaded={got.current} />
        <div className="max-h-72 w-full overflow-y-auto p-2">
          <Table fixed>
            <TableHeader className="sticky top-0 bg-white dark:bg-gray-900">
              <TableRow>
                {["coin", "PROFIT $", "trades", "W", "L", "win %"].map((h) => (
                  <TableCell key={h} isHeader className="px-2 py-1.5 text-theme-xs font-medium text-gray-500 text-start dark:text-gray-400">{h}</TableCell>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
              {coinRows.map(([coin, v]) => (
                <TableRow key={coin}>
                  <TableCell className="px-2 py-1.5 text-theme-xs font-medium text-gray-800 dark:text-white/90">{coin.replace("_USDT", "")}</TableCell>
                  <TableCell className={`px-2 py-1.5 text-theme-xs font-semibold ${v.pnl >= 0 ? "text-success-600" : "text-error-500"}`}>{fmtMoney(v.pnl)}</TableCell>
                  <TableCell className="px-2 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{v.trades}</TableCell>
                  <TableCell className="px-2 py-1.5 text-theme-xs text-success-600">{v.wins}</TableCell>
                  <TableCell className="px-2 py-1.5 text-theme-xs text-error-500">{v.losses}</TableCell>
                  <TableCell className="px-2 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{v.trades ? ((v.wins / v.trades) * 100).toFixed(1) : "—"}</TableCell>
                </TableRow>
              ))}
              {!coinRows.length && !loading && <TableRow><TableCell className="px-3 py-4 text-theme-sm text-gray-500 dark:text-gray-400">No closed trades on this book yet.</TableCell></TableRow>}
            </TableBody>
          </Table>
        </div>
      </div>

      <DayCalendar days={loading ? {} : days} loading={loading}
        book={dry ? "practice account" : "real-money account"} dry={dry} onBook={pick} />
    </div>
  );
}

function Spinner() {
  return <span aria-hidden className="inline-block h-3.5 w-3.5 shrink-0 animate-spin rounded-full border-2 border-brand-500 border-t-transparent" />;
}

function Loading({ what }: { what: string }) {
  return <span className="inline-flex items-center gap-2" role="status"><Spinner />loading the {what}…</span>;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const pad2 = (n: number) => String(n).padStart(2, "0");
/** The key `daily_pnl` files a day under: the LOCAL "YYYY-MM-DD". */
const dayKey = (y: number, m: number, d: number) => `${y}-${pad2(m + 1)}-${pad2(d)}`;

/** DAY BY DAY AS A CALENDAR (operator, Sep 27, 2026: *"in day by day section
 * can you create calendar and show me the pnl for day insteead"*). One month
 * at a time, each day its own box with that day's closed profit, and the
 * month's total summed from the same boxes, so the caption cannot disagree
 * with the grid. A day with no closed trade stays blank rather than +0.00:
 * "nothing closed" and "closed at break-even" are different days. */
export function DayCalendar({ days, book, dry, onBook, loading = false }: {
  days: Record<string, DayStat>; book: string; dry?: boolean; onBook?: (dry: boolean) => void;
  loading?: boolean;
}) {
  const now = new Date();
  const [month, setMonth] = useState({ y: now.getFullYear(), m: now.getMonth() });
  const [picked, setPicked] = useState<string | null>(null);

  const keys = Object.keys(days).sort();
  const first = keys[0];
  const firstY = first ? Number(first.slice(0, 4)) : month.y;
  const firstM = first ? Number(first.slice(5, 7)) - 1 : month.m;
  const canBack = month.y * 12 + month.m > firstY * 12 + firstM;
  const canNext = month.y * 12 + month.m < now.getFullYear() * 12 + now.getMonth();
  const step = (n: number) => {
    const t = month.y * 12 + month.m + n;
    setMonth({ y: Math.floor(t / 12), m: t % 12 });
    setPicked(null);
  };

  const lead = new Date(month.y, month.m, 1).getDay();
  const count = new Date(month.y, month.m + 1, 0).getDate();
  const cells: (number | null)[] = [...Array(lead).fill(null),
    ...Array.from({ length: count }, (_, i) => i + 1)];
  while (cells.length % 7) cells.push(null);

  const inMonth = Array.from({ length: count }, (_, i) => days[dayKey(month.y, month.m, i + 1)])
    .filter((v): v is DayStat => !!v);
  const total = inMonth.reduce((a, v) => a + v.pnl, 0);
  const wins = inMonth.reduce((a, v) => a + v.wins, 0);
  const losses = inMonth.reduce((a, v) => a + v.losses, 0);
  const green = inMonth.filter((v) => v.pnl > 0).length;
  const todayKey = dayKey(now.getFullYear(), now.getMonth(), now.getDate());
  const sel = picked ? days[picked] : undefined;

  return (
    <div className="min-w-0 overflow-hidden rounded-2xl border border-gray-200 bg-white dark:border-white/[0.05] dark:bg-white/[0.03]">
      <div className="flex items-center gap-2 px-5 pt-4">
        <h3 className="text-base font-semibold text-gray-800 dark:text-white/90">Day by day</h3>
        <div className="ml-auto flex items-center gap-1">
          <button type="button" aria-label="previous month" disabled={!canBack} onClick={() => step(-1)}
            className="h-8 w-8 rounded-lg border border-gray-200 text-gray-600 disabled:opacity-30 dark:border-gray-700 dark:text-gray-300">‹</button>
          <span className="w-20 text-center text-theme-sm font-medium text-gray-700 dark:text-gray-200">{MONTHS[month.m]} {month.y}</span>
          <button type="button" aria-label="next month" disabled={!canNext} onClick={() => step(1)}
            className="h-8 w-8 rounded-lg border border-gray-200 text-gray-600 disabled:opacity-30 dark:border-gray-700 dark:text-gray-300">›</button>
        </div>
      </div>
      {onBook && (
        <div className="flex gap-1 px-5 pb-1 pt-2">
          {([[false, "Real money"], [true, "Practice"]] as const).map(([v, label]) => (
            <button key={label} type="button" onClick={() => onBook(v)}
              className={`rounded-lg border px-3 py-1 text-theme-xs font-medium ${dry === v
                ? "border-brand-500 bg-brand-500 text-white"
                : "border-gray-200 text-gray-600 dark:border-gray-700 dark:text-gray-300"}`}>{label}</button>
          ))}
        </div>
      )}
      <p className="px-5 text-theme-xs text-gray-500 dark:text-gray-400">
        {loading ? <Loading what={book} /> : <>
        {book} · {MONTHS[month.m]} {month.y}:{" "}
        <span className={`font-semibold ${total >= 0 ? "text-success-600" : "text-error-500"}`}>{fmtMoney(total)}</span>
        {" · "}{wins}W / {losses}L · {green} of {inMonth.length} trading days green
        </>}
      </p>
      <div className="relative p-3">
        {loading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center">
            <span className="flex items-center gap-2 rounded-full bg-white px-4 py-2 text-theme-sm font-medium text-gray-700 shadow dark:bg-gray-900 dark:text-gray-200">
              <Spinner />loading…
            </span>
          </div>
        )}
        <div className={`grid grid-cols-7 gap-1 transition-opacity ${loading ? "animate-pulse opacity-40" : ""}`}>
          {WEEKDAYS.map((w) => (
            <div key={w} className="py-1 text-center text-[10px] font-medium uppercase tracking-wide text-gray-400">{w}</div>
          ))}
          {cells.map((d, i) => {
            if (d == null) return <div key={`b${i}`} />;
            const k = dayKey(month.y, month.m, d);
            const v = days[k];
            const tone = !v ? "border-gray-100 dark:border-white/[0.05]"
              : v.pnl >= 0 ? "border-success-200 bg-success-50 dark:border-success-500/30 dark:bg-success-500/10"
              : "border-error-200 bg-error-50 dark:border-error-500/30 dark:bg-error-500/10";
            return (
              <button key={k} type="button" disabled={!v} onClick={() => setPicked(picked === k ? null : k)}
                className={`flex min-h-14 min-w-0 flex-col items-stretch rounded-lg border p-1 text-start ${tone}
                  ${k === todayKey ? "ring-2 ring-brand-500" : ""} ${picked === k ? "outline outline-2 outline-gray-700 dark:outline-white" : ""}`}>
                <span className="text-[10px] text-gray-500 dark:text-gray-400">{d}</span>
                {v && <>
                  {/* a phone box is ~40px: whole dollars there, cents from md
                      up and always in the line under the grid when tapped */}
                  <span className={`text-[11px] font-semibold tabular-nums ${v.pnl >= 0 ? "text-success-600" : "text-error-500"}`}>
                    <span className="md:hidden">{Math.abs(v.pnl) >= 10 ? `${v.pnl >= 0 ? "+" : "-"}${Math.round(Math.abs(v.pnl))}` : fmtMoney(v.pnl)}</span>
                    <span className="hidden md:inline">{fmtMoney(v.pnl)}</span>
                  </span>
                  <span className="flex flex-wrap gap-x-1 text-[9px] leading-tight">
                    <span className="text-success-600">{v.wins}W</span><span className="text-error-500">{v.losses}L</span>
                  </span>
                </>}
              </button>
            );
          })}
        </div>
        {sel && picked && (
          <p className="mt-2 rounded-lg bg-gray-50 px-3 py-2 text-theme-xs text-gray-600 dark:bg-white/[0.03] dark:text-gray-300">
            <b>{MONTHS[Number(picked.slice(5, 7)) - 1]} {picked.slice(8, 10)}, {picked.slice(0, 4)}</b>{" · "}
            <span className={sel.pnl >= 0 ? "text-success-600" : "text-error-500"}>{fmtMoney(sel.pnl)}</span>
            {" · "}{sel.trades} trade{sel.trades === 1 ? "" : "s"}, {sel.wins}W / {sel.losses}L · {sel.coins.join(", ")}
          </p>
        )}
        {!keys.length && !loading && <p className="mt-2 text-theme-sm text-gray-500 dark:text-gray-400">No closed trades on the {book} yet{dry ? "" : " — tap Practice to see the practice trades"}.</p>}
      </div>
    </div>
  );
}
