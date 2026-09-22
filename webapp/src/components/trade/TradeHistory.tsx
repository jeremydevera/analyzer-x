"use client";
/** Every CLOSED trade, LIVE and DEMO on their own tabs.
 *
 * Five rows a page, numbered — a wall of 200 rows hides a trade as
 * effectively as a net figure does. The running total is computed over the
 * whole book, so page 3's "running $" is the real one, not the page's.
 */
import { useEffect, useState } from "react";
import { markReady } from "@/lib/loading";
import { useLiveRefresh } from "@/lib/live";
import CopyableId from "./CopyableId";
import PanelStatus from "./PanelStatus";
import { fmtMoney, HistoryPayload, tradeApi } from "@/lib/api";
import { Table, TableBody, TableCell, TableHeader, TableRow } from "@/components/ui/table";

// id and opened lead the row: the operator asked to be able to name a
// trade and see when it started (2026-08-22).
const HEADS = ["id", "opened", "closed", "held", "coin", "side", "strategy",
               "closed by", "PROFIT $", "running $"];
// While a search is on, rows from BOTH books sit in one table, so the table
// has to say which is which. Without it the same id appears twice and reads
// as a duplicate rather than as the two copies of one trade.
const HEADS_SEARCH = ["book", ...HEADS];

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
  // FIND A TRADE BY ID, ACROSS BOTH BOOKS. Operator, Sep 17, 2026: "in trade
  // history, put a id search there, when i search LG9NSU4B for example it
  // should show trade id LG9NSU4B for both live and demo trade".
  //
  // `q` goes to the SERVER. It must never become a .filter() over `d.rows`
  // here: the server sends five rows a page, so a browser-side filter would
  // search the PAGE instead of the book — the exact shape that hid a KITE
  // loss 640 rows past the window a panel had fetched (CLAUDE.md, filter
  // where the data is).
  const [q, setQ] = useState("");
  const searching = q.trim().length > 0;

  // EVERY 5 SECONDS, and the instant the tab is looked at again. It used to
  // load ONCE and re-fetch only after a failure, so a trade that closed while
  // the page was open never appeared here — the operator's live PSXSTOCK stop
  // at Sep 10, 2026 8:04pm was in the ledger and not on this table until a
  // reload: *"i want the ui realtime ... currently i need to refresh it"*.
  // The old self-healing retry is kept by the same loop: a failed fetch is
  // simply the next tick's job (an API restart's few dark seconds, Sep 09).
  useLiveRefresh(() => {
    tradeApi.history(dry, page, 5, q.trim())
      .then((r) => { setD(r); setErr(""); markReady("trade history"); })
      .catch((e) => setErr(String(e)));
  }, 5_000, [dry, page, q]);

  useEffect(() => { setPage(1); }, [dry, q]);

  const t = d?.totals;
  return (
    <div className="min-w-0 overflow-hidden rounded-2xl border border-gray-200 bg-white dark:border-white/[0.05] dark:bg-white/[0.03]">
      <div className="flex flex-wrap items-center gap-3 px-5 pt-4">
        <div>
          <h3 className="text-base font-semibold text-gray-800 dark:text-white/90">Trade history</h3>
          <p className="text-theme-xs text-gray-500 dark:text-gray-400">
            {searching
              ? (d
                  ? `${d.total} trade${d.total === 1 ? "" : "s"} matching `
                    + `${d.q ?? q} on BOTH books, of ${d.examined ?? 0} closed`
                  : "searching both books")
              : `every closed trade${d ? ` · ${d.total} on this book` : ""}`}
            {t && t.trades ? ` · ${t.wins}W / ${t.losses}L · ${fmtMoney(t.profit)} total` : ""}
          </p>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {/* Type a trade id or a strategy id — with or without the #, either
              case. A search covers BOTH books, so the live/demo tabs go quiet
              while one is running rather than pretending to still apply. */}
          <div className="relative">
            <input value={q} onChange={(e) => setQ(e.target.value)}
              id="trade-history-search"
              placeholder="find by id, e.g. LG9NSU4B"
              className="h-8 w-56 rounded-lg border border-gray-200 bg-transparent px-2 pr-7 font-mono text-theme-xs text-gray-700 placeholder:font-sans placeholder:text-gray-400 dark:border-gray-700 dark:text-gray-300" />
            {searching && (
              <button type="button" onClick={() => setQ("")} title="clear the search"
                className="absolute right-1 top-1 h-6 w-6 rounded text-theme-xs text-gray-400 hover:text-gray-700 dark:hover:text-gray-200">
                ×
              </button>
            )}
          </div>
          <div className={`flex gap-1 rounded-lg bg-gray-100 p-1 dark:bg-white/[0.06] ${searching ? "opacity-40" : ""}`}>
            {([[false, "LIVE — real money"], [true, "DEMO — simulated"]] as const).map(([v, lab]) => (
              <button key={String(v)} onClick={() => setDry(v)} disabled={searching}
                title={searching ? "a search covers both books" : undefined}
                className={`rounded-md px-3 py-1 text-theme-xs font-medium transition ${dry === v && !searching
                  ? (v ? "bg-white text-gray-800 shadow-theme-xs dark:bg-gray-800 dark:text-white/90"
                       : "bg-error-500 text-white")
                  : "text-gray-500 dark:text-gray-400"}`}>
                {lab}
              </button>
            ))}
          </div>
        </div>
      </div>
      <PanelStatus err={err} loaded={d !== null} />

      {/* PHONE: CARDS, NOT A TABLE (operator, Sep 23, 2026, reading this on
          their phone over Tailscale: "the live trade table is not mobile
          responsive").

          Ten columns on a 390px screen is 39px each. The `Table` component is
          built to WRAP rather than scroll sideways (`table-fixed` +
          `break-words`, and its own comment says the Auto Trade screen must
          not scroll sideways) — but every cell here carries
          `whitespace-nowrap`, which defeats that, so the text was simply
          clipped by the card's `overflow-hidden`. Wrapping instead would put
          "Sep 22, 2026 9:34am" into a 39px column one character wide.

          So below `md` the same rows are stacked as cards, headline first:
          what it made, on what, which way. The table is unchanged above `md`,
          because on a desktop ten columns side by side is the point. */}
      <div className="flex flex-col gap-2 px-4 pb-2 md:hidden">
        {(d?.rows ?? []).map((r, i) => (
          <div key={`m-${r.ts}-${i}`}
            className="rounded-xl border border-gray-200 p-3 dark:border-white/[0.07]">
            <div className="flex items-start justify-between gap-2">
              <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                {searching && (
                  <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${r.book === "demo"
                    ? "bg-gray-100 text-gray-600 dark:bg-white/[0.08] dark:text-gray-300"
                    : "bg-error-50 text-error-600 dark:bg-error-500/15 dark:text-error-400"}`}>
                    {r.book === "demo" ? "demo" : "live"}
                  </span>
                )}
                <span className="text-theme-sm font-medium text-gray-800 dark:text-white/90">
                  {r.coin}
                </span>
                <span className={`text-theme-xs ${r.side === "LONG" ? "text-success-600" : "text-error-500"}`}>
                  {r.side}
                </span>
                {r.why ? (
                  <span className="text-theme-xs text-gray-500 dark:text-gray-400">· {r.why}</span>
                ) : null}
              </div>
              {/* the money leads, because it is the one thing read first */}
              <span className={`shrink-0 text-theme-sm font-semibold ${r.profit >= 0 ? "text-success-600" : "text-error-500"}`}>
                {fmtMoney(r.profit)}
              </span>
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-theme-xs text-gray-500 dark:text-gray-400">
              {r.id ? (
                <button title="copy this trade's id"
                  onClick={() => { navigator.clipboard?.writeText(String(r.id)); }}
                  className="font-mono text-gray-700 hover:underline dark:text-gray-300">
                  {r.id}
                </button>
              ) : null}
              {r.strategy_id ? <CopyableId id={r.strategy_id} /> : null}
              <span className="min-w-0 break-words">{r.strategy}</span>
            </div>
            <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-theme-xs text-gray-500 dark:text-gray-400">
              <span>opened {r.opened ?? "—"}</span>
              <span>closed {r.when}</span>
              {r.held ? <span>held {r.held}</span> : null}
              <span className={r.running >= 0 ? "text-success-600" : "text-error-500"}>
                running {fmtMoney(r.running)}
              </span>
            </div>
          </div>
        ))}
        {/* THE EMPTY STATE RENDERS HERE TOO. It lives inside the table body,
            so hiding the table on a phone would have hidden the sentence that
            says what was searched — an empty screen speaking for nothing
            (CLAUDE.md, Sep 12, 2026). */}
        {d && !d.rows.length && (
          <p className="py-3 text-theme-sm text-gray-500 dark:text-gray-400">
            {searching
              ? `No trade or strategy id matching ${d.q ?? q} in the `
                + `${d.examined ?? 0} closed trades on either book — `
                + "ids are 8 characters, and the # is optional."
              : `No closed trades on the ${dry ? "demo" : "live"} book yet.`}
          </p>
        )}
      </div>

      <div className="hidden w-full md:block">
        <Table fixed>
          <TableHeader className="border-b border-gray-100 dark:border-white/[0.05]">
            <TableRow>
              {(searching ? HEADS_SEARCH : HEADS).map((h) => (
                <TableCell key={h} isHeader className="px-2 py-1.5 text-theme-xs font-medium text-gray-500 text-start dark:text-gray-400">{h}</TableCell>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
            {(d?.rows ?? []).map((r, i) => (
              <TableRow key={`${r.ts}-${i}`}>
                {searching && (
                  <TableCell className="whitespace-nowrap px-2 py-1.5 text-theme-xs">
                    <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${r.book === "demo"
                      ? "bg-gray-100 text-gray-600 dark:bg-white/[0.08] dark:text-gray-300"
                      : "bg-error-50 text-error-600 dark:bg-error-500/15 dark:text-error-400"}`}>
                      {r.book === "demo" ? "demo" : "live"}
                    </span>
                  </TableCell>
                )}
                <TableCell className="whitespace-nowrap px-2 py-1.5 font-mono text-theme-xs text-gray-800 dark:text-white/90">
                  {/* the SAME id the open position carries, so a trade can be
                      followed from open to closed by one string (operator,
                      Sep 10, 2026) */}
                  {r.id ? (
                    <button title="copy this trade's id"
                      onClick={() => { navigator.clipboard?.writeText(String(r.id)); }}
                      className="font-mono hover:underline">{r.id}</button>
                  ) : "—"}
                </TableCell>
                <TableCell className="whitespace-nowrap px-2 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{r.opened ?? "—"}</TableCell>
                <TableCell className="whitespace-nowrap px-3 py-2 text-theme-xs text-gray-500 dark:text-gray-400">{r.when}</TableCell>
                <TableCell className="whitespace-nowrap px-2 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{r.held ?? "—"}</TableCell>
                <TableCell className="px-2 py-1.5 text-theme-xs font-medium text-gray-800 dark:text-white/90">{r.coin}</TableCell>
                <TableCell className={`px-2 py-1.5 text-theme-xs ${r.side === "LONG" ? "text-success-600" : "text-error-500"}`}>{r.side}</TableCell>
                {/* the strategy AND its own id (operator, Sep 10, 2026: "in
                    trade history expose the strategy id as well") — the same
                    #code the strategies grid and the positions table print,
                    through the same copy control, so a closed trade can be
                    traced to the row that took it */}
                <TableCell className="px-2 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">
                  {r.strategy_id ? <CopyableId id={r.strategy_id} /> : null}
                  <span className="block leading-tight">{r.strategy}</span>
                </TableCell>
                <TableCell className="px-2 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{r.why}</TableCell>
                <TableCell className={`px-2 py-1.5 text-theme-xs font-semibold ${r.profit >= 0 ? "text-success-600" : "text-error-500"}`}>{fmtMoney(r.profit)}</TableCell>
                <TableCell className={`px-2 py-1.5 text-theme-xs ${r.running >= 0 ? "text-success-600" : "text-error-500"}`}>{fmtMoney(r.running)}</TableCell>
              </TableRow>
            ))}
            {d && !d.rows.length && (
              <TableRow><TableCell className="px-3 py-4 text-theme-sm text-gray-500 dark:text-gray-400">
                {/* AN EMPTY ANSWER NAMES WHAT IT CHECKED. "nothing found" over
                    a store nobody counted is the failure CLAUDE.md records for
                    Sep 12, 2026, where a panel spoke for 893,508 rows after
                    examining 25. */}
                {searching
                  ? `No trade or strategy id matching ${d.q ?? q} in the `
                    + `${d.examined ?? 0} closed trades on either book — `
                    + "ids are 8 characters, and the # is optional."
                  : `No closed trades on the ${dry ? "demo" : "live"} book yet.`}
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
