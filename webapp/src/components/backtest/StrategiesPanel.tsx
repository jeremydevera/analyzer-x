"use client";
/**
 * Every stored strategy, filtered — and the trades behind any row on click.
 * The trade log is cross-checked in the UI: its footer sums the rows it
 * shows, and a drift beyond 2% against the stored row is SAID, not hidden
 * (the label-must-match-data rule, ported).
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, fmtMoney, STRATEGY_SORTS, StrategyRow, TradesResult,
  type IndexStatus, type StrategySort } from "@/lib/api";
import { pageWindow } from "@/lib/pager";
import Badge from "@/components/ui/badge/Badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const pageNum =
  "h-8 min-w-8 rounded-lg border px-2 text-theme-xs tabular-nums";

const pageBtn =
  "h-8 rounded-lg border border-gray-300 px-2 text-theme-xs text-gray-600 " +
  "disabled:opacity-40 dark:border-gray-700 dark:text-gray-300";

const sel =
  "h-10 rounded-lg border border-gray-300 bg-transparent px-3 text-theme-sm " +
  "text-gray-700 focus:outline-hidden focus:ring-2 focus:ring-brand-500/20 " +
  "dark:border-gray-700 dark:bg-gray-900 dark:text-gray-300";

/** Which order a clicked header stands for. Built FROM STRATEGY_SORTS, so
 *  the header text, the caption and the query can never disagree — the
 *  "win % ↓" marker used to be decoration: clicking it did nothing
 *  (operator, 2026-08-26). */
// rows a page. The operator asked to see the whole store, so the page size
// is theirs to choose and LOAD MORE keeps appending; MAX_LIMIT (5,000) is
// the server's ceiling per request, and the CSV has none at all.
const PAGE_SIZES = [100, 500, 1000, 5000];

/** The header of the window's own profit column. Not sortable: the store ranks
 *  by the full-history columns it has indexes for, and a header that reordered
 *  only the rows on screen is the "it only sorted the page" lie (2026-08-26). */
/** Column headers when a window is on: the ones the store can restate exactly
 *  for every row (profit, green) and the ones that need the row's log rebuilt
 *  (trades, W, L, win %). Marked either way, because a column labelled
 *  `PROFIT $` while showing two months of it is the label-must-match-data
 *  failure this repo keeps paying for. */
const winHead = (h: string, months: number) =>
  months > 0 ? `${h} (${months}mo)` : h;

const HEAD_SORT: Record<string, StrategySort | undefined> =
  Object.fromEntries(Object.entries(STRATEGY_SORTS)
    .map(([k, label]) => [label, k as StrategySort]));

export default function StrategiesPanel() {
  const [facets, setFacets] = useState<{ coins: string[]; tfs: string[]; signals: string[]; tps?: number[]; sizings?: string[] }>({ coins: [], tfs: [], signals: [], tps: [], sizings: [] });
  const [coin, setCoin] = useState("");
  const [tf, setTf] = useState("");
  const [signal, setSignal] = useState("");
  const [profitable, setProfitable] = useState(false);
  const [sort, setSort] = useState<StrategySort>("profit");
  // ranking by win % on the real store put "100.00% over 1 trade" first,
  // so picking win % asks for a denominator (editable, and said out loud)
  const [minTrades, setMinTrades] = useState(0);
  // "add a textbox winrate, if i put 50 then show me coins with winrate equal
  // or greater than 50" (operator, 2026-08-27). It takes the unit the win %
  // column PRINTS — 50 means 50.00% or better, inclusive (CLAUDE.md rule G) —
  // and it runs in the STORE, not on the page: filtering the 500 rows on
  // screen would hide the 70%-win row sitting at position 900,000.
  const [minWinrate, setMinWinrate] = useState(0);
  // "add filter 'TP' when i input 4 then show that has TP equal or greater
  // than 4" (operator, 2026-08-27). TP is the profit target a winning trade
  // aims at, so 4 means "only strategies going for 4% a trade or more" — the
  // unit the TP% column prints, inclusive.
  const [minTp, setMinTp] = useState(0);
  // "i want filter to see flat / martingale" (operator, 2026-08-27). Sizing is
  // HOW MUCH is staked per trade: flat stakes the same every time, martingale
  // doubles after a loss to win it back. It is a sizing choice, not a
  // measurement — an audit proved the "13/13 green months" behind six live
  // strategies came from the ladder, not the signal (flat: 7/12–11/12,
  // CLAUDE.md rule 19) — so the two have to be visible apart.
  const [sizing, setSizing] = useState("");
  // GROUP: the ten researched confluence setups (every rule named cf_..., three
  // levels each) against the 75 signals that existed before them. The
  // operator's own names, 2026-08-27: "Preset Confluence" / "Classic".
  const [group, setGroup] = useState("");
  // "add filter to input a specific id, it should get speicic id example
  // #6YACZSXX" (operator, 2026-08-27) — and CLAUDE.md kit item H, where
  // quoting a row by its code is what stops the wrong config being deployed.
  // The id is HASHED FROM THE COMBINATION, so it names one coin × timeframe ×
  // signal × threshold × SL/TP × sizing and nothing else: it OVERRIDES the
  // other filters rather than joining them, and opens that row's trades.
  const [rowId, setRowId] = useState("");
  // "add filter Last x month / if i entered 2 months then adjust the number of
  // trades, winrate, profit for last x month" (operator, 2026-08-27) and
  // CLAUDE.md kit item G. The store keeps PROFIT per month (fast_grid and
  // auto_trader both accumulate `monthly[month] += pnl` and nothing else), so
  // the window's profit and months-green are exact and its trade count is not
  // — that one needs the row's trades rebuilt, which a click already does.
  const [months, setMonths] = useState(0);
  // the window the SERVER used, in real month keys — never the box's number
  const [window_, setWindow] = useState<string[]>([]);
  // the floors the SERVER actually applied. On a 503 the request moves and the
  // rows do not, so captioning them with the request is the lie the operator
  // read as "it only sorted the page" (label-must-match-data).
  const [servedTrades, setServedTrades] = useState(0);
  const [servedWinrate, setServedWinrate] = useState(0);
  const [servedTp, setServedTp] = useState(0);
  // "ranking by win % needs its index" is a WAIT, not a failure: keep the
  // rows on screen, say the sentence the API said, and come back for it
  const [waiting, setWaiting] = useState("");
  // which end of the column: a second click on the same header flips it
  const [desc, setDesc] = useState(true);
  // The order the SERVER SERVED, which is the only thing the rows on screen
  // are actually in. `sort`/`desc` are the REQUEST: when the store answers
  // 503 because an index is still building, the request moves and the rows
  // do not, and captioning them with the request is a lie the operator
  // read as "it only sorted the page" (2026-08-26).
  const [servedSort, setServedSort] = useState<StrategySort>("profit");
  const [servedDesc, setServedDesc] = useState(true);
  // 21,858,026 rows behind a 300-row window with no way to reach row 301:
  // "why is my stored strategy few ... where are those?" (2026-08-26)
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(500);
  // LOAD MORE appends instead of replacing, so the table becomes one long
  // list rather than a window that forgets what came before
  const [extra, setExtra] = useState<StrategyRow[]>([]);
  const [loadingMore, setLoadingMore] = useState(false);
  // "if i set a winrate its very slow can you show if its loading so i know
  // its loading same as for other filters becuase i thought its not working,
  // its just loading" (operator, 2026-08-27). A win % floor ranked by win %
  // took 30.3 s on this store COLD (35,863,520 rows, mechanical disk) and the
  // panel sat there showing the PREVIOUS rows with nothing moving — the same
  // screen a broken filter would give. So: say it is working, and count the
  // seconds so the operator can see it still is.
  const [loading, setLoading] = useState(false);
  // "i want a button 'Apply filters' so i know its loading" (operator,
  // 2026-08-27). The boxes above are a DRAFT; this is what the store was
  // actually asked for. Typing used to fire a request per keystroke — on this
  // store a win % floor takes 30.3 s cold, so typing "50" asked for >=5 and
  // then >=50 and the screen showed whichever landed last. Now the request
  // leaves when the operator says so, and the button is where the spinner is.
  const [applied, setApplied] = useState({
    coin: "", tf: "", signal: "", profitable: false,
    minTrades: 0, minWinrate: 0, minTp: 0, sizing: "", rowId: "", group: "",
    months: 0,
  });
  // The filter set the ROWS ON SCREEN came from — set only when a request
  // SUCCEEDS. `applied` is what was asked for, and the two differ every time a
  // request fails: measured 2026-08-27, `tf=1h AND trades>=120 AND win%>=55
  // AND TP>=4` ranked by profit answered HTTP 500 (the proxy gives up at 30 s,
  // and top-profit rows are martingale rows winning 11-15% of the time, so the
  // profit index has to be walked a long way to find 500 that pass). The old
  // rows stayed on screen — and the filter line said they matched the new
  // filters. A label describing data it did not come from is the failure this
  // repo keeps paying for (label-must-match-data).
  const [servedFilters, setServedFilters] = useState({
    coin: "", tf: "", signal: "", profitable: false,
    minTrades: 0, minWinrate: 0, minTp: 0, sizing: "", rowId: "", group: "",
    months: 0,
  });
  // how long the request that FAILED had been running, so the message can say
  // "did not answer in 34s" instead of a bare HTTP 500
  const [failedAfter, setFailedAfter] = useState(0);
  const [waited, setWaited] = useState(0);
  // The spinner waits 300 ms before appearing. The list re-polls itself every
  // 5 s while the indexer is behind, and a pill that blinks on every one of
  // those reads as a glitch; a filter that answers in 40 ms never needed a
  // spinner at all. Anything the operator has to WAIT for crosses 300 ms.
  const [showLoad, setShowLoad] = useState(false);
  // Which request an answer belongs to. Once a query can take 30 s, two typed
  // in a row can come back in either order, and the SLOWER older one would
  // overwrite the newer rows under a caption that says otherwise.
  const reqRef = useRef(0);
  // is a request on the wire? A background refresh must not queue behind a
  // slow one and it must not restart the seconds counter
  const inFlight = useRef(false);
  const [reindexing, setReindexing] = useState("");
  const [rows, setRows] = useState<StrategyRow[]>([]);
  const [total, setTotal] = useState(0);
  // a filtered count stops at rows_index.COUNT_CAP, so the caption says
  // "5,000+ match" rather than a bare 5,000 that reads as exact
  const [capped, setCapped] = useState(false);
  const [open, setOpen] = useState<StrategyRow | null>(null);
  const [trades, setTrades] = useState<TradesResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [idx, setIdx] = useState<IndexStatus | null>(null);

  useEffect(() => {
    api.facets().then(setFacets).catch((e) => setErr(String(e)));
  }, []);

  // The widest TP this store can hold, from the measuring grid for the
  // timeframes it actually has (facets.tps) — NOT a round number picked here.
  // The box stops there on purpose: `tp` has no index, so asking for a TP no
  // row has costs a scan of all 35,863,520 rows to answer "nothing", measured
  // at over 25 s for tp >= 10 (which lives only in the 1d grid).
  const tpCeiling = facets.tps?.length ? Math.max(...facets.tps) : 100;

  /** `background` = a timer asked, not the operator. Same request, same rows,
   *  no spinner: the button belongs to the click. */
  const load = useCallback((background = false) => {
    const mine = ++reqRef.current;
    inFlight.current = true;
    if (!background) setLoading(true);
    api.strategies({ coin: applied.coin || undefined, tf: applied.tf || undefined,
                     signal: applied.signal || undefined,
                     profitable: applied.profitable, sort,
                     minTrades: applied.minTrades, minWinrate: applied.minWinrate,
                     minTp: applied.minTp, sizing: applied.sizing || undefined,
                     rowId: applied.rowId || undefined,
                     months: applied.months || undefined,
                     group: (applied.group || undefined) as "preset" | "classic" | undefined,
                     desc, limit: perPage, offset: (page - 1) * perPage })
      .then((d) => {
        if (mine !== reqRef.current) return;   // a newer request owns the screen
        setRows(d.rows); setTotal(d.total); setCapped(!!d.total_capped);
        setIdx(d.index ?? null); setErr(""); setWaiting("");
        // what the rows are really in, straight from the payload
        setServedSort((d.sort as StrategySort) ?? sort);
        setServedDesc(d.desc ?? desc);
        setServedTrades(d.min_trades ?? applied.minTrades);
        setServedWinrate(d.min_winrate ?? applied.minWinrate);
        setServedTp(d.min_tp ?? applied.minTp);
        setServedFilters(applied);   // these rows came from THIS set
        setWindow(d.window ?? []);   // the window's real months, from the payload
        setFailedAfter(0);
      })
      .catch((e) => {
        if (mine !== reqRef.current) return;
        setFailedAfter(waited);
        if (e instanceof ApiError && e.status === 503) {
          setWaiting(e.detail || "the index for this order is being built");
          setErr("");
        } else { setErr(String(e)); setWaiting(""); }
      })
      .finally(() => {
        inFlight.current = false;
        if (mine === reqRef.current) setLoading(false);
      });
  }, [applied, sort, desc, page, perPage]);

  useEffect(load, [load]);
  // the elapsed seconds, so a 30-second answer visibly PROGRESSES instead of
  // looking like a dead screen. Reset when the request ends.
  useEffect(() => {
    if (!loading) { setWaited(0); setShowLoad(false); return; }
    const started = Date.now();
    const gate = setTimeout(() => setShowLoad(true), 300);
    const tick = setInterval(
      () => setWaited(Math.round((Date.now() - started) / 1000)), 500);
    return () => { clearTimeout(gate); clearInterval(tick); };
  }, [loading]);
  // a new filter or order is a new list: page 1, or the operator lands on
  // page 40 of something they have not seen the top of
  // an ORDER change is instant, so it resets the page here; a FILTER change
  // resets it in `apply`, where the request is actually sent
  useEffect(() => { setPage(1); setExtra([]); }, [sort, desc, perPage]);
  useEffect(() => {
    if (!waiting) return;
    const t = setTimeout(() => { if (!inFlight.current) load(true); }, 15000);
    return () => clearTimeout(t);
  }, [waiting, load]);
  useEffect(() => {
    if (!idx || (!idx.syncing && idx.behind === 0)) return;
    const t = setTimeout(() => { if (!inFlight.current) load(true); }, 5000);
    return () => clearTimeout(t);
  }, [idx, load]);

  const shown = rows.concat(extra);
  // An id names ONE row and the reason to look it up is its trade log, so a
  // hit opens it (kit item H). Keyed on the row so it fires once per lookup.
  const idHit = servedFilters.rowId && rows.length === 1 ? rows[0] : null;
  useEffect(() => {
    if (idHit && open?.id !== idHit.id) view(idHit);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idHit?.id]);
  // what the boxes say right now, against what the store was asked
  const draft = { coin, tf, signal, profitable, minTrades, minWinrate, minTp,
                  sizing, group, months,
                  // trim FIRST: " #6yaczsxx " pasted from chat kept its hash
                  // when the # was stripped before the spaces, and a real id
                  // then read as "not in the store"
                  rowId: rowId.trim().replace(/^#+/, "").trim().toUpperCase() };
  const pending = (Object.keys(draft) as (keyof typeof draft)[])
    .filter((k) => draft[k] !== applied[k]);
  /** send the boxes to the store. Page 1, because a new filter is a new list
   *  and the operator would otherwise land on page 40 of something they have
   *  not seen the top of. */
  const apply = () => { setApplied(draft); setPage(1); setExtra([]); };
  const onFilterKey = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") apply();
  };
  /** The filter set as ONE sentence, ANDed, in the operator's own reading:
   *  "all coins AND all timeframe AND all signals AND min trades =x AND min
   *  win% = x". Built from a set of terms, so a box that is added and not
   *  named here would be visibly missing rather than silently unmentioned. */
  const andLine = (f: typeof draft) => (f.rowId
    ? `row #${f.rowId} — every other filter ignored, an id names one row`
    : [
    f.coin || "all coins",
    f.tf || "all timeframes",
    f.signal || "all signals",
    f.group === "preset" ? "group = Preset Confluence"
      : f.group === "classic" ? "group = Classic" : "all groups",
    f.minTrades > 0 ? `min trades = ${f.minTrades}` : "any trades",
    f.minWinrate > 0 ? `min win % = ${f.minWinrate}` : "any win %",
    f.minTp > 0 ? `min TP % = ${f.minTp}` : "any TP",
    f.sizing ? `sizing = ${f.sizing}` : "flat and martingale",
    f.profitable ? "profit > 0" : "losers included",
    f.months > 0 ? `last ${f.months} month${f.months > 1 ? "s" : ""}`
                 : "all history",
  ].join(" AND "));
  // The REQUEST in words — what the spinner is waiting for, not what is on
  // screen (the caption already says that). The SAME sentence the filter line
  // prints, so "AND" means the same thing everywhere on this panel, and it
  // reads `applied` because that is what was actually sent.
  const asking = `${andLine(applied)} — ${desc ? "highest" : "lowest"} `
    + `${STRATEGY_SORTS[sort]} first`;
  // asked for, not served, and nothing in flight — i.e. the request failed
  const missed = !loading && (Object.keys(applied) as (keyof typeof applied)[])
    .some((k) => applied[k] !== servedFilters[k]);
  /** The month columns. Newest first, and DERIVED: from the window the server
   *  used when there is one, otherwise from the months the rows on screen
   *  actually carry. Kit item G — months outside the window are REMOVED, not
   *  printed as em dashes. */
  const monthCols = (window_.length
    ? window_
    : Array.from(new Set(shown.flatMap((r) => Object.keys(r.monthly ?? {}))))
        .sort().reverse()).slice(0, 24);
  /** "2026-08" -> "Aug 2026". A month LABEL keeps its own form (CLAUDE.md);
   *  the operator's example was "month of aug, july". */
  const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const monthLabel = (k: string) => {
    const [y, m] = k.split("-");
    return `${MONTH_NAMES[Number(m) - 1] ?? m} ${y}`;
  };
  /** What to PRINT for a row: the window's figures when there is a window and
   *  the server had them, the row's own otherwise. Profit and green come from
   *  the stored per-month profits (exact for every row); trades, W, L and win %
   *  exist only where the row's log was rebuilt (`restated`). */
  const win = (r: StrategyRow) => (servedFilters.months > 0
    ? {profit: r.w_profit ?? 0,
       trades: r.restated ? r.w_trades : r.trades,
       wins: r.restated ? r.w_wins : r.wins,
       losses: r.restated ? r.w_losses : r.losses,
       winrate: r.restated ? r.w_winrate : r.winrate}
    : {profit: r.profit, trades: r.trades, wins: r.wins, losses: r.losses,
       winrate: r.winrate});
  const stale = (r: StrategyRow) => servedFilters.months > 0 && !r.restated;
  const STALE_WHY = "the whole history, not the window: the sweep stores profit "
    + "per month but not trades, so this row's log has to be rebuilt. Look one "
    + "row up by #id and it is restated.";
  const pages = Math.max(1, Math.ceil(total / perPage));
  // a numbered page is a jump, so the appended LOAD MORE rows go with it —
  // otherwise page 7 shows page 6's tail underneath it
  const goto = (n: number) => {
    // a CAPPED count is a floor, not the end: `pages` would pin the
    // operator to page 10 of a filter that really has 4,000, so only an
    // exact total is allowed to be a ceiling
    setPage(capped ? Math.max(1, n) : Math.min(Math.max(1, n), pages));
    setExtra([]);
  };

  /** the coins missing from the list are measured, just not indexed yet */
  const catchUp = async () => {
    setReindexing("asking…");
    try {
      const d = await api.strategiesReindex();
      setReindexing(d.why);
      api.strategies({ limit: 1 }).catch(() => {});
    } catch (e) { setReindexing(String(e)); }
  };

  const loadMore = async () => {
    setLoadingMore(true);
    try {
      const d = await api.strategies({
        coin: applied.coin || undefined, tf: applied.tf || undefined,
        signal: applied.signal || undefined, profitable: applied.profitable,
        sort, minTrades: applied.minTrades, minWinrate: applied.minWinrate,
        minTp: applied.minTp, sizing: applied.sizing || undefined,
        rowId: applied.rowId || undefined,
        months: applied.months || undefined, desc,
        limit: perPage, offset: (page - 1) * perPage + shown.length,
      });
      setExtra((e) => e.concat(d.rows));
    } catch (e) { setErr(String(e)); } finally { setLoadingMore(false); }
  };

  const view = async (r: StrategyRow) => {
    setOpen(r);
    setTrades(null);
    setBusy(true);
    try {
      setTrades(await api.trades(r));
    } catch (e) {
      setTrades({ log: [], why: String(e) });
    } finally {
      setBusy(false);
    }
  };

  /** the trades inside the window, by their EXIT month — a trade opened in
   *  July and closed in August belongs to August's profit, which is how the
   *  sweep counts it too (`monthly[_month_of(exit_bar)] += pnl`). */
  const inWindow = (t: { "exit time": string }) => {
    if (!window_.length) return true;
    // "Aug 03, 2026 8:03pm" — the project's one date format
    const m = /^([A-Za-z]{3}) \d{2}, (\d{4})/.exec(t["exit time"] || "");
    if (!m) return true;                    // never hide a row we cannot place
    const mm = MONTH_NAMES.indexOf(m[1]) + 1;
    return window_.includes(`${m[2]}-${String(mm).padStart(2, "0")}`);
  };
  const winLog = (trades?.log ?? []).filter(inWindow);
  const winWins = winLog.filter((t) => t["pnl $"] > 0).length;
  const winSum = winLog.reduce((a, t) => a + (t["pnl $"] ?? 0), 0);
  const logSum = trades?.log?.reduce((a, t) => a + (t["pnl $"] ?? 0), 0) ?? 0;
  const drift =
    open && trades && trades.log.length
      ? Math.abs((trades.profit ?? logSum) - (open.profit ?? 0)) >
        Math.max(1, Math.abs(open.profit ?? 0) * 0.02)
      : false;

  return (
    <div className="overflow-hidden rounded-2xl border border-gray-200 bg-white dark:border-white/[0.05] dark:bg-white/[0.03]">
      <div className="flex flex-wrap items-end gap-3 px-5 pt-4">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-base font-semibold text-gray-800 dark:text-white/90">Stored strategies</h3>
            {/* The operator's own sentence: "i thought its not working, its
                just loading". A spinner, WHAT it is waiting for, and how long
                it has been waiting. `role=status` so it is announced too. */}
            {showLoad && (
              <span role="status" aria-live="polite"
                    className="inline-flex items-center gap-2 rounded-full bg-brand-50 px-2.5 py-1 text-theme-xs font-medium text-brand-600 dark:bg-brand-500/15 dark:text-brand-400">
                <span aria-hidden="true"
                      className="h-3 w-3 animate-spin rounded-full border-2 border-brand-500 border-t-transparent" />
                {/* the row count is the INDEX's own (idx.rows), never a
                    literal that drifts as the store grows */}
                searching {idx?.rows ? `${idx.rows.toLocaleString()}-row ` : ""}store…
                {waited >= 1 ? ` ${waited}s` : ""}
              </span>
            )}
          </div>
          <p className="text-theme-xs text-gray-500 dark:text-gray-400">
            {total.toLocaleString()}{capped ? "+" : ""} {[applied.coin, applied.tf, applied.signal, applied.profitable ? "profitable only" : ""].some(Boolean) || applied.minTrades > 0 || applied.minWinrate > 0 || applied.minTp > 0 ? "match" : "stored strategies"}
            {` · rows ${shown.length ? (page - 1) * perPage + 1 : 0}–${(page - 1) * perPage + shown.length} on screen`}
            {` · ${servedDesc ? "highest" : "lowest"} ${STRATEGY_SORTS[servedSort]} first`}
            {/* A partial index must NOT be captioned as the whole store: the
                sweep measures pairs faster than they are indexed, and "648,181
                stored strategies" while 40 pairs are still queued is a false
                label on a true number. */}
            {idx && (idx.behind > 0 || idx.syncing) ? (
              <span className="text-warning-600 dark:text-warning-400">
                {" · "}indexing {idx.pairs_indexed.toLocaleString()} of{" "}
                {idx.pairs_on_disk.toLocaleString()} measured pairs — this list is
                still filling in
              </span>
            ) : null}
            {/* how many CONTRACTS are in the list, asked 2026-08-26 — from the
                facets the dropdowns already loaded, so it cannot disagree with
                what the coin filter offers */}
            {facets.coins.length ? ` · ${facets.coins.length.toLocaleString()} coins` : ""}
            {facets.tfs.length ? ` · ${facets.tfs.length} timeframes` : ""}
            {facets.signals.length ? ` · ${facets.signals.length} signals` : ""}
            {[applied.coin, applied.tf, applied.signal].filter(Boolean).length ? ` · filters: ${[applied.coin, applied.tf, applied.signal].filter(Boolean).join(" · ")}` : ""}
            {applied.profitable ? " · profitable only" : " · losers included"}
            {servedTrades > 0 ? ` · at least ${servedTrades} trades` : ""}
            {servedWinrate > 0 ? ` · win % ${servedWinrate} or better` : ""}
            {servedTp > 0 ? ` · TP ${servedTp}% or wider` : ""}
            {servedFilters.sizing ? ` · ${servedFilters.sizing} only` : ""}
            {window_.length
              ? ` · window ${monthLabel(window_[window_.length - 1])}–${monthLabel(window_[0])}`
              : ""}
          </p>
          {/* while a slow filter runs, the numbers above still describe the
              PREVIOUS answer — so say out loud which request is in flight
              rather than letting the old caption stand for the new filter */}
          {showLoad && (
            <p className="text-theme-xs text-brand-600 dark:text-brand-400">
              loading {asking} — the figures above are still the previous
              answer{waited >= 8 ? "; a win % or TP floor can take 30s+ on this store" : ""}
            </p>
          )}
        </div>
        {idx && idx.behind > 0 ? (
          <button onClick={catchUp} disabled={!!reindexing}
            className="h-10 rounded-lg border border-warning-500 px-3 text-theme-sm font-medium text-warning-600 hover:bg-warning-50 disabled:opacity-50 dark:text-warning-400">
            {reindexing || `index the missing ${idx.behind.toLocaleString()} pair(s) now`}
          </button>
        ) : null}
        <div className="ml-auto flex flex-wrap gap-2">
          {/* LAST N MONTHS — "if i entered 2 months then adjust the number of
              trades, winrate, profit for last x month". 0 is everything the
              store holds. The window's real month keys come back in the
              payload, so the caption prints dates, not the number typed. */}
          <label className="flex h-10 items-center gap-2 text-theme-sm text-gray-700 dark:text-gray-300"
                 title="re-state every row over the last N months: its own profit and green months inside that window, and only those month columns">
            last
            <input type="number" min={0} max={24} step={1} value={months}
                   onChange={(e) => setMonths(Math.min(24, Math.max(0, Number(e.target.value) || 0)))}
                   onKeyDown={onFilterKey}
                   aria-label="Last N months"
                   className="h-10 w-16 rounded-lg border border-gray-300 bg-transparent px-2 text-theme-sm text-gray-700 focus:outline-hidden focus:ring-2 focus:ring-brand-500/20 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-300" />
            month(s)
          </label>
          {/* "#6YACZSXX" — the code the first column prints. Typed with or
              without the #, any case; it overrides the rest. */}
          <label className="flex h-10 items-center gap-2 text-theme-sm text-gray-700 dark:text-gray-300"
                 title="find one row by the id in its first column — this overrides the other filters">
            #id
            <input type="text" value={rowId} placeholder="6YACZSXX"
                   onChange={(e) => setRowId(e.target.value)}
                   onKeyDown={onFilterKey}
                   aria-label="Row id"
                   className="h-10 w-28 rounded-lg border border-gray-300 bg-transparent px-2 font-mono text-theme-sm uppercase text-gray-700 focus:outline-hidden focus:ring-2 focus:ring-brand-500/20 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-300" />
          </label>
          <select className={sel} value={coin} onChange={(e) => setCoin(e.target.value)} aria-label="Coin">
            <option value="">all coins</option>
            {facets.coins.map((c) => <option key={c}>{c}</option>)}
          </select>
          <select className={sel} value={tf} onChange={(e) => setTf(e.target.value)} aria-label="Timeframe">
            <option value="">all timeframes</option>
            {facets.tfs.map((t) => <option key={t}>{t}</option>)}
          </select>
          {/* GROUP: the ten researched confluence setups — every rule named
              cf_..., ten setups at three levels each — against the 75 signals
              that existed before them. The operator's names, 2026-08-27. */}
          <select className={sel} value={group}
                  onChange={(e) => setGroup(e.target.value)} aria-label="Group">
            <option value="">all groups</option>
            <option value="preset">Preset Confluence</option>
            <option value="classic">Classic</option>
          </select>
          <select className={sel} value={signal} onChange={(e) => setSignal(e.target.value)} aria-label="Signal">
            <option value="">all signals</option>
            {facets.signals.map((s) => <option key={s}>{s}</option>)}
          </select>
          {/* "i want filter to see flat / martingale". The options come from
              the grid that measured the rows (facets.sizings), so the dropdown
              cannot offer a sizing the store does not hold. */}
          <select className={sel} value={sizing}
                  onChange={(e) => setSizing(e.target.value)}
                  aria-label="Sizing">
            <option value="">flat and martingale</option>
            {(facets.sizings ?? []).map((z) => (
              <option key={z} value={z}>{z} only</option>
            ))}
          </select>
          <label className="flex h-10 items-center gap-2 text-theme-sm text-gray-700 dark:text-gray-300">
            min trades
            <input type="number" min={0} step={10} value={minTrades}
                   onChange={(e) => setMinTrades(Math.max(0, Number(e.target.value) || 0))}
                   aria-label="Minimum trades"
                   onKeyDown={onFilterKey}
                   className="h-10 w-20 rounded-lg border border-gray-300 bg-transparent px-2 text-theme-sm text-gray-700 focus:outline-hidden focus:ring-2 focus:ring-brand-500/20 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-300" />
          </label>
          {/* the operator's own sentence: "if i put 50 then show me coins with
              winrate equal or greater than 50" — a COUNT-free percentage box,
              in the unit the win % column prints */}
          <label className="flex h-10 items-center gap-2 text-theme-sm text-gray-700 dark:text-gray-300"
                 title="show only rows whose win % is this or higher">
            min win %
            <input type="number" min={0} max={100} step={5} value={minWinrate}
                   onChange={(e) => setMinWinrate(Math.min(100, Math.max(0, Number(e.target.value) || 0)))}
                   aria-label="Minimum win rate percent"
                   onKeyDown={onFilterKey}
                   className="h-10 w-20 rounded-lg border border-gray-300 bg-transparent px-2 text-theme-sm text-gray-700 focus:outline-hidden focus:ring-2 focus:ring-brand-500/20 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-300" />
          </label>
          {/* "when i input 4 then show that has TP equal or greater than 4":
              the take-profit target, in the unit the TP% column prints. The
              list offers the values the grid really measured, so 4, 5, 6 and 8
              are one keystroke away and 9.37 is not typed by accident. */}
          <label className="flex h-10 items-center gap-2 text-theme-sm text-gray-700 dark:text-gray-300"
                 title={`show only rows whose take-profit is this % or wider (this store measured up to ${tpCeiling}%)`}>
            min TP %
            <input type="number" min={0} max={tpCeiling} step={0.5} value={minTp}
                   list="tp-values"
                   onChange={(e) => setMinTp(Math.min(tpCeiling, Math.max(0, Number(e.target.value) || 0)))}
                   aria-label="Minimum take profit percent"
                   onKeyDown={onFilterKey}
                   className="h-10 w-20 rounded-lg border border-gray-300 bg-transparent px-2 text-theme-sm text-gray-700 focus:outline-hidden focus:ring-2 focus:ring-brand-500/20 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-300" />
            <datalist id="tp-values">
              {(facets.tps ?? []).map((v) => <option key={v} value={v} />)}
            </datalist>
          </label>
          <label className="flex h-10 items-center gap-2 text-theme-sm text-gray-700 dark:text-gray-300">
            <input type="checkbox" checked={profitable} onChange={(e) => setProfitable(e.target.checked)} className="h-4 w-4 accent-brand-500" />
            profitable only
          </label>
          {/* "i want a button 'Apply filters' so i know its loading". The
              button IS the progress: it names what it is doing and for how
              long, so a 30-second store read cannot look like a dead screen.
              It also says when the boxes differ from what is on screen. */}
          <button type="button" onClick={apply}
                  disabled={loading || !pending.length}
                  aria-live="polite"
                  className="inline-flex h-10 items-center gap-2 rounded-lg bg-brand-500 px-4 text-theme-sm font-medium text-white hover:bg-brand-600 disabled:cursor-not-allowed disabled:bg-gray-300 dark:disabled:bg-gray-700">
            {loading ? (
              <>
                <span aria-hidden="true"
                      className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/60 border-t-transparent" />
                searching{waited >= 1 ? ` ${waited}s` : "…"}
              </>
            ) : pending.length ? (
              `Apply ${pending.length} filter${pending.length > 1 ? "s" : ""}`
            ) : "Apply filters"}
          </button>
          {pending.length && !loading ? (
            <span className="flex h-10 items-center text-theme-xs text-warning-600 dark:text-warning-400">
              {pending.length} change{pending.length > 1 ? "s" : ""} not applied yet
            </span>
          ) : null}
        </div>
      </div>
      {/* Every box narrows the SAME rows: they are ANDed, in SQL and here.
          The line reads the DRAFT — what Apply will send — and says when that
          is not yet what the table shows. */}
      <div className="px-5 pt-3">
        <p className="text-theme-xs text-gray-600 dark:text-gray-300">
          {/* the ROWS' own set, never the request's: a failed request leaves
              the two different, and this line describes the table */}
          <span className="font-medium">showing rows where:</span>{" "}
          {andLine(servedFilters)}
          {pending.length ? (
            <span className="text-warning-600 dark:text-warning-400">
              {" "}— Apply filters will ask for {andLine(draft)}
            </span>
          ) : missed ? (
            <span className="text-error-500">
              {" "}— {andLine(applied)} was asked for and did not come back
              {failedAfter >= 1 ? ` (${failedAfter}s)` : ""}
            </span>
          ) : null}
        </p>
      </div>
      {/* one row IS one combination — the operator's own words: "under those
          coins i have multiple strategy and under that strategy is different
          timeframe and combinations of tp and sl". Say so, and page through. */}
      <div className="flex flex-wrap items-center gap-2 px-5 pt-3">
        <span className="text-theme-xs text-gray-500 dark:text-gray-400">
          one row = one coin × timeframe × signal × threshold × SL/TP × sizing
          {" · "}
          <span title="Profit is the anchor: a row that did not make money rates 1-3 whatever its win rate. A profitable one starts at 4 and earns up to 10 on profit per trade, win rate, green months and whether its take-profit clears the round-trip cost; it loses points for a dip bigger than what it earned, for a dip over 10x the stake, and for losing most of its trades (the ladder carrying the signal). Under 30 trades it cannot rate above 4, under 100 not above 7. Hover any score for its own working.">
            <b>balanced</b> rates win rate AND profit together, 1-10 (hover a
            score for the working)
          </span>
        </span>
        <div className="ml-auto flex flex-wrap items-center gap-1">
          <select className={`${pageBtn} mr-1`} value={perPage}
                  onChange={(e) => setPerPage(Number(e.target.value))}
                  aria-label="Rows per page">
            {PAGE_SIZES.map((n) => <option key={n} value={n}>{n.toLocaleString()} a page</option>)}
          </select>
          <button onClick={() => goto(page - 1)} disabled={page <= 1}
                  className={pageBtn}>prev</button>
          {pageWindow(page, pages).map((n, i) => n == null ? (
            <span key={`gap${i}`} aria-hidden
                  className="px-1 text-theme-xs text-gray-400">…</span>
          ) : (
            <button key={n} onClick={() => goto(n)}
                    aria-label={`page ${n}`}
                    aria-current={n === page ? "page" : undefined}
                    className={`${pageNum} ${n === page
                      ? "border-brand-500 bg-brand-500 font-semibold text-white"
                      : "border-gray-300 text-gray-600 hover:border-brand-400 dark:border-gray-700 dark:text-gray-300"}`}>
              {n.toLocaleString()}
            </button>
          ))}
          <button onClick={() => goto(page + 1)}
                  disabled={rows.length < perPage}
                  className={pageBtn}>next</button>
          <input type="number" min={1} placeholder="page #"
                 aria-label="Go to page"
                 onKeyDown={(e) => {
                   if (e.key !== "Enter") return;
                   const n = Number((e.target as HTMLInputElement).value);
                   if (n >= 1) goto(n);
                 }}
                 className={`${pageBtn} w-20`} />
          <span className="text-theme-xs text-gray-500 dark:text-gray-400">
            of {pages.toLocaleString()}{capped ? "+" : ""}
          </span>
          <button onClick={loadMore} disabled={loadingMore}
                  className={`${pageBtn} ml-1`}>
            {loadingMore ? "loading…" : `+${perPage.toLocaleString()} more`}
          </button>
          {/* the only honest "all": a file, streamed, with every column */}
          <a className={`${pageBtn} ml-1 inline-flex items-center`}
             /* the APPLIED set, not the boxes: the link's own label is the
                applied count ("download all (5,000+) CSV"), so a draft-based
                href would hand over a different slice than it names */
             href={api.strategiesCsvUrl({ coin: applied.coin || undefined,
               tf: applied.tf || undefined, signal: applied.signal || undefined,
               profitable: applied.profitable, sort,
               minTrades: applied.minTrades, minWinrate: applied.minWinrate,
               minTp: applied.minTp, sizing: applied.sizing || undefined,
               rowId: applied.rowId || undefined, desc })}>
            download all ({total.toLocaleString()}{capped ? "+" : ""}) CSV
          </a>
        </div>
      </div>
      {/* What the window CAN and CANNOT re-state. The sweep stores profit per
          month (`monthly[month] += pnl`) and nothing else, so trades, W, L and
          win % on this page are the row's WHOLE history even while the window
          is on — saying which is which is the difference between a filter and
          a false label. The row's own trade log is the exact answer for one
          row, because it is rebuilt from the candles. */}
      {window_.length > 0 && (
        <p className="px-5 pt-2 text-theme-xs text-gray-600 dark:text-gray-300">
<b>PROFIT $</b> and <b>green</b> are the window&apos;s own for every row
          ({window_.length} month{window_.length > 1 ? "s" : ""}:{" "}
          {window_.map(monthLabel).join(", ")}) — summed from the per-month
          profits the sweep stored, so they are exact.{" "}
          <b>trades, W, L and win %</b> need this row&apos;s trades rebuilt from
          the candles (the sweep keeps profit per month, not trades), which
          takes about a second a row — so they are the window&apos;s on a{" "}
          <b>single row</b> and the whole history, in grey italics, on the rest.
          Type the row&apos;s <b>#id</b> to restate all five.
        </p>
      )}
      {err && (
        <p className="px-5 pt-2 text-theme-sm text-error-500">
          {err}
          {/* HTTP 500 after half a minute is not a bug report, it is a
              timeout: the proxy in front of the API gives up at 30 s. Say
              which query did it and what makes it cheap again. */}
          {failedAfter >= 20 ? (
            <span className="block text-theme-xs">
              the store did not answer in {failedAfter}s and the proxy gave up
              at 30s. A win % floor ranked by <b>{STRATEGY_SORTS[sort]}</b> has
              to walk the profit index a long way — the biggest profits are
              martingale rows winning 11–15% of the time. Narrow it with a coin
              or a timeframe, or rank by <b>win %</b> (click that header), which
              reads the win-rate index instead.
            </span>
          ) : null}
        </p>
      )}
      {/* rule G: a filter that cannot leave anything says why, rather than
          showing an empty table the reader has to explain to themselves */}
      {!err && !waiting && !shown.length && !!servedFilters.rowId && !missed && (
        <p className="px-5 pt-2 text-theme-sm text-warning-600 dark:text-warning-400">
          no row <b>#{servedFilters.rowId}</b> in the store. The id is hashed
          from the combination, so it changes if the row was re-measured with
          different barriers — check it against the first column of the table
          or the artifact you copied it from.
        </p>
      )}
      {!err && !waiting && !shown.length && !servedFilters.rowId && (minWinrate > 0 || minTrades > 0 || minTp > 0) && (
        <p className="px-5 pt-2 text-theme-sm text-warning-600 dark:text-warning-400">
          no stored strategy passes{" "}
          <b>
            {[minWinrate > 0 ? `win % ≥ ${minWinrate}` : "",
              minTp > 0 ? `TP ≥ ${minTp}%` : "",
              minTrades > 0 ? `${minTrades}+ trades` : ""]
              .filter(Boolean).join(" with ")}
          </b>
          {[coin, tf, signal].filter(Boolean).length ? ` and ${[coin, tf, signal].filter(Boolean).join(" · ")}` : ""}
          {profitable ? " and profit above zero" : ""} — lower the floor to see what is close.
        </p>
      )}
      {waiting && (
        <p className="px-5 pt-2 text-theme-sm text-warning-600 dark:text-warning-400">
          preparing <b>{STRATEGY_SORTS[sort]}</b> across all {total.toLocaleString()}
          {capped ? "+" : ""} rows — {waiting}. Until it lands these rows are
          still ordered by <b>{STRATEGY_SORTS[servedSort]}</b>; the list
          refreshes by itself.
        </p>
      )}
      {/* taller than 480px: with 5,000 rows on screen the old box showed
          about nine of them at a time */}
      {/* aria-busy + a dim: the rows under a running request are last
          request's rows, and they must not look freshly served */}
      <div aria-busy={loading}
           className={`max-h-[75vh] max-w-full overflow-auto p-2 transition-opacity ${
             showLoad ? "opacity-40" : ""}`}>
        <Table>
          <TableHeader className="sticky top-0 border-b border-gray-100 bg-white dark:border-white/[0.05] dark:bg-gray-900">
            <TableRow>
              {["id", "coin", "tf", "signal", "th%", "SL%", "TP%", "sizing", "lev", "margin $",
                winHead("PROFIT $", servedFilters.months),
                winHead("win %", servedFilters.months),
                winHead("trades", servedFilters.months),
                winHead("W", servedFilters.months),
                winHead("L", servedFilters.months),
                winHead("green", servedFilters.months),
                "dip $",
                winHead("balanced", servedFilters.months),
                ...monthCols.map(monthLabel)].map((h) => (
                <TableCell key={h} isHeader
                  onClick={() => {
                    const next = HEAD_SORT[h.replace(/ \(\d+mo\)$/, "")];
                    if (!next) return;          // not a sortable column
                    if (next === sort) { setDesc(!desc); return; }
                    setSort(next);
                    setDesc(next !== "dd");     // smallest dip is the useful end
                    // A rate needs a denominator; a profit does not. Clicking a
                    // header re-runs the query AT ONCE (it is not one of the
                    // Apply filters), so the floor has to be applied in the same
                    // breath — a draft-only 100 would let the store rank by win %
                    // with no floor and answer "100.00% over 1 trade", which is
                    // what that box exists to prevent.
                    if (next === "winrate" && applied.minTrades === 0) {
                      setMinTrades(100);
                      setApplied((a) => ({ ...a, minTrades: 100 }));
                      setPage(1); setExtra([]);
                    }
                  }}
                  className={`px-3 py-3 text-theme-xs font-medium text-start ${
                    HEAD_SORT[h.replace(/ \(\d+mo\)$/, "")] ? "cursor-pointer select-none hover:text-brand-600" : ""} ${
                    h.replace(/ \(\d+mo\)$/, "") === STRATEGY_SORTS[servedSort]
                      ? "text-brand-600 dark:text-brand-400"
                      : h.replace(/ \(\d+mo\)$/, "") === STRATEGY_SORTS[sort]
                        ? "text-warning-600 dark:text-warning-400"
                        : "text-gray-500 dark:text-gray-400"}`}
                  title={HEAD_SORT[h.replace(/ \(\d+mo\)$/, "")]
                    ? `sort every row by ${h} — the ORDER is always over the whole history the store has`
                    : undefined}>
                  {h}{h.replace(/ \(\d+mo\)$/, "") === STRATEGY_SORTS[servedSort]
                        ? (servedDesc ? " ↓" : " ↑")
                     : h.replace(/ \(\d+mo\)$/, "") === STRATEGY_SORTS[sort] ? " …" : ""}
                </TableCell>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
            {/* the rows on screen came from `servedFilters`; when that is
                not what was asked for, they are last question's answer and
                showing them under this question's filters is the lie the
                operator caught (2026-08-27) */}
            {missed ? (
              <TableRow>
                <TableCell colSpan={17}
                           className="px-3 py-6 text-theme-sm text-gray-500 dark:text-gray-400">
                  {applied.rowId
                    ? <>row <b>#{applied.rowId}</b> has not come back</>
                    : <>no rows for {andLine(applied)} yet</>}
                  {" — "}
                  {/* the store's OWN sentence when it gave one (a 503 says
                      which index is building); otherwise say what happened */}
                  {waiting || `the store did not answer${
                    failedAfter >= 1 ? ` in ${failedAfter}s` : ""}`}
                  . The previous answer is not shown here because it does not
                  match {applied.rowId ? "that id" : "these filters"}.
                </TableCell>
              </TableRow>
            ) : null}
            {!missed && shown.map((r) => (
              <TableRow key={r.id} onClick={() => view(r)}
                className={`cursor-pointer hover:bg-gray-50 dark:hover:bg-white/[0.03] ${open?.id === r.id ? "bg-brand-50 dark:bg-brand-500/10" : ""}`}>
                <TableCell className="px-3 py-2 font-mono text-theme-xs text-brand-600 dark:text-brand-400">#{r.id}</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm font-medium text-gray-800 dark:text-white/90">{r.coin}</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{r.tf}</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm font-medium text-gray-800 dark:text-white/90">{r.signal}</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{r.th ?? 0}</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{r.sl}</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{r.tp}</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{r.sizing}</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{r.lev ?? 20}x</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{r.base ?? 5} ({r.notional ?? 100} ntl)</TableCell>
                {/* PROFIT is the WINDOW'S profit when a window is on — summed
                    from the per-month profits the sweep stored, exact for every
                    row on the page. The full-history figure is in the title. */}
                <TableCell className={`px-3 py-2 text-theme-sm font-semibold ${(win(r).profit ?? 0) >= 0 ? "text-success-600" : "text-error-500"}`}
                           title={servedFilters.months > 0
                             ? `${fmtMoney(r.profit)} over the whole history the store has`
                             : undefined}>
                  {fmtMoney(win(r).profit)}
                </TableCell>
                {/* trades / W / L / win % are the WINDOW'S only where the
                    server could rebuild this row's log. Where it could not they
                    are the whole history and they are DIMMED and titled, never
                    printed as if they belonged to the window. */}
                <TableCell className={`px-3 py-2 text-theme-sm ${stale(r) ? "italic text-gray-400 dark:text-gray-500" : "text-gray-500 dark:text-gray-400"}`}
                           title={stale(r) ? STALE_WHY : undefined}>
                  {win(r).winrate?.toFixed(2)}
                </TableCell>
                <TableCell className={`px-3 py-2 text-theme-sm ${stale(r) ? "italic text-gray-400 dark:text-gray-500" : "text-gray-500 dark:text-gray-400"}`}
                           title={stale(r) ? STALE_WHY : undefined}>
                  {win(r).trades}
                </TableCell>
                <TableCell className={`px-3 py-2 text-theme-sm ${stale(r) ? "italic text-gray-400 dark:text-gray-500" : "text-success-600"}`}
                           title={stale(r) ? STALE_WHY : undefined}>
                  {win(r).wins}
                </TableCell>
                <TableCell className={`px-3 py-2 text-theme-sm ${stale(r) ? "italic text-gray-400 dark:text-gray-500" : "text-error-500"}`}
                           title={stale(r) ? STALE_WHY : undefined}>
                  {win(r).losses}
                </TableCell>
                <TableCell className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">
                  {servedFilters.months > 0
                    ? `${r.w_green ?? 0}/${r.w_months ?? 0}`
                    : `${r.green ?? "—"}/${r.months ?? "—"}`}
                </TableCell>
                <TableCell className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{r.dd?.toFixed(2) ?? "—"}</TableCell>
                {/* BALANCED, 1-10 over win rate AND profit. The tooltip is the
                    working — "sometimes it has high winrate but since tp is low
                    and sl is high, its still not profitable" is a number the
                    operator has to be able to audit. Dimmed with the window on
                    and the row not restated, because then the score mixes the
                    window's profit with the row's whole-history win rate. */}
                <TableCell className={`px-3 py-2 text-theme-sm font-semibold ${
                    stale(r) ? "italic text-gray-400 dark:text-gray-500"
                    : (r.balanced ?? 0) >= 8 ? "text-success-600"
                    : (r.balanced ?? 0) >= 5 ? "text-warning-600 dark:text-warning-400"
                    : "text-error-500"}`}
                  title={stale(r)
                    ? `${r.balanced_why ?? ""} — ${STALE_WHY}`
                    : (r.balanced_why ?? "")}>
                  {r.balanced === undefined ? "—" : r.balanced.toFixed(1)}/10
                </TableCell>
                {/* one column per month, the row's own profit in it. A month
                    the row never traded is an em dash — that is missing DATA,
                    not a hidden column (the columns themselves are the
                    window's, see monthCols). */}
                {monthCols.map((k) => {
                  const v = (r.monthly ?? {})[k];
                  return (
                    <TableCell key={k}
                      className={`px-3 py-2 text-theme-sm ${
                        v === undefined ? "text-gray-400 dark:text-gray-500"
                        : v >= 0 ? "text-success-600" : "text-error-500"}`}>
                      {v === undefined ? "—" : fmtMoney(v)}
                    </TableCell>
                  );
                })}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {open && (
        <div className="border-t border-gray-100 px-5 py-4 dark:border-white/[0.05]">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <span className="font-mono text-theme-sm text-brand-600 dark:text-brand-400">#{open.id}</span>
            <span className="text-theme-sm font-medium text-gray-800 dark:text-white/90">
              {open.coin} {open.tf} {open.signal} · SL {open.sl}% / TP {open.tp}% · {open.sizing}
            </span>
            {busy && <Badge size="sm" color="info">rebuilding trades…</Badge>}
            {trades && trades.log.length > 0 && (
              <>
                <Badge size="sm" color="primary">{trades.trades} trades</Badge>
                <Badge size="sm" color="success">{trades.wins} WIN</Badge>
                <Badge size="sm" color="error">{trades.losses} LOSE</Badge>
                <Badge size="sm" color={(trades.profit ?? 0) >= 0 ? "success" : "error"}>
                  TOTAL {fmtMoney(trades.profit ?? logSum)} USDT
                </Badge>
                {/* the window's OWN trades, wins and win % — counted from the
                    rebuilt log, which is the only place they exist */}
                {window_.length > 0 && (
                  <Badge size="sm" color="info">
                    last {window_.length} month{window_.length > 1 ? "s" : ""}:{" "}
                    {winLog.length} trades · {winWins} W /{" "}
                    {winLog.length - winWins} L ·{" "}
                    {winLog.length
                      ? ((100 * winWins) / winLog.length).toFixed(2)
                      : "0.00"}% win · {fmtMoney(winSum)} USDT
                  </Badge>
                )}
              </>
            )}
          </div>
          {drift && (
            <p className="mb-2 text-theme-sm text-warning-600">
              These trades total {fmtMoney(trades?.profit ?? logSum)} but the stored row says {fmtMoney(open.profit)} —
              the candle store has grown since the row was measured. Run BACKTEST to refresh it.
            </p>
          )}
          {trades && trades.why && !trades.log.length && (
            <p className="text-theme-sm text-gray-500 dark:text-gray-400">{trades.why}</p>
          )}
          {trades && trades.log.length > 0 && (
            <div className="max-h-80 max-w-full overflow-auto">
              <Table>
                <TableHeader className="sticky top-0 bg-white dark:bg-gray-900">
                  <TableRow>
                    {["opened", "closed", "side", "closed by", "entry", "exit", "rung", "margin $", "funding $", "W/L", "pnl $", "running $"].map((h) => (
                      <TableCell key={h} isHeader className="px-3 py-2 text-theme-xs font-medium text-gray-500 text-start dark:text-gray-400">{h}</TableCell>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
                  {trades.log.map((t, i) => (
                    <TableRow key={i}>
                      <TableCell className="px-3 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{t["entry time"]}</TableCell>
                      <TableCell className="px-3 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{t["exit time"]}</TableCell>
                      <TableCell className="px-3 py-1.5 text-theme-xs text-gray-700 dark:text-gray-300">{t.side}</TableCell>
                      <TableCell className="px-3 py-1.5 text-theme-xs font-medium text-gray-700 dark:text-gray-300">{t.why}</TableCell>
                      <TableCell className="px-3 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{t.entry}</TableCell>
                      <TableCell className="px-3 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{t.exit}</TableCell>
                      <TableCell className="px-3 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{t.step}</TableCell>
                      <TableCell className="px-3 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{t["margin $"]}</TableCell>
                      <TableCell className="px-3 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{t["funding $"] ?? 0}</TableCell>
                      <TableCell className={`px-3 py-1.5 text-theme-xs font-semibold ${t["WIN/LOSE"] === "WIN" ? "text-success-600" : "text-error-500"}`}>{t["WIN/LOSE"]}</TableCell>
                      <TableCell className={`px-3 py-1.5 text-theme-xs ${t["pnl $"] >= 0 ? "text-success-600" : "text-error-500"}`}>{fmtMoney(t["pnl $"])}</TableCell>
                      <TableCell className="px-3 py-1.5 text-theme-xs text-gray-500 dark:text-gray-400">{fmtMoney(t["running total $"])}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <p className="mt-2 text-theme-xs text-gray-500 dark:text-gray-400">
                Log sum {fmtMoney(logSum)} USDT over {trades.log.length} trades — losers cost{" "}
                {fmtMoney(trades.log.filter((t) => t["pnl $"] <= 0).reduce((a, t) => a + t["pnl $"], 0))}, wins earned{" "}
                {fmtMoney(trades.log.filter((t) => t["pnl $"] > 0).reduce((a, t) => a + t["pnl $"], 0))}.
              </p>
              {/* WHAT WAS READ, and over WHICH DAYS. The operator found a Sep 02
                  trade under a row measured to Aug 27 (2026-09-02): the click
                  used to download the newest candles first. It reads stored
                  candles now and stops where the row stopped — and when the row
                  predates that stamp, this line says the window came from the
                  pair's watermark instead, which is why a trade or two can
                  differ. */}
              {trades.first && (
                <p className="mt-1 text-theme-xs text-gray-400 dark:text-gray-500">
                  Rebuilt from {trades.source ?? "stored candles"} — {trades.bars?.toLocaleString()} bars,{" "}
                  {trades.first} to {trades.last}
                  {trades.window_from === "row"
                    ? " (the window this row was measured over)"
                    : " (this row predates the per-row window stamp, so the end comes from the pair's last update — a trade or two may differ until it is re-measured)"}
                  . Nothing was downloaded.
                  {trades.fee !== undefined && (
                    <>
                      {" "}Fee charged {(trades.fee * 100).toFixed(3)}%{" "}
                      {trades.fee_from === "row"
                        ? "— the fee this row was measured with."
                        : "— the venue's fee TODAY; this row does not record what it was charged, and a contract's fee changes (PONS went 0.02% → 0.04%, worth 21% of one row's profit), so the total here can differ from the row until it is re-measured."}
                    </>
                  )}
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
