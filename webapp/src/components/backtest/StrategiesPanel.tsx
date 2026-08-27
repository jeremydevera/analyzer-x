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

const HEAD_SORT: Record<string, StrategySort | undefined> =
  Object.fromEntries(Object.entries(STRATEGY_SORTS)
    .map(([k, label]) => [label, k as StrategySort]));

export default function StrategiesPanel() {
  const [facets, setFacets] = useState<{ coins: string[]; tfs: string[]; signals: string[]; tps?: number[] }>({ coins: [], tfs: [], signals: [], tps: [] });
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
    minTrades: 0, minWinrate: 0, minTp: 0,
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
    minTrades: 0, minWinrate: 0, minTp: 0,
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

  const load = useCallback(() => {
    const mine = ++reqRef.current;
    setLoading(true);
    api.strategies({ coin: applied.coin || undefined, tf: applied.tf || undefined,
                     signal: applied.signal || undefined,
                     profitable: applied.profitable, sort,
                     minTrades: applied.minTrades, minWinrate: applied.minWinrate,
                     minTp: applied.minTp, desc,
                     limit: perPage, offset: (page - 1) * perPage })
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
      .finally(() => { if (mine === reqRef.current) setLoading(false); });
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
    const t = setTimeout(load, 15000);
    return () => clearTimeout(t);
  }, [waiting, load]);
  useEffect(() => {
    if (!idx || (!idx.syncing && idx.behind === 0)) return;
    const t = setTimeout(load, 5000);
    return () => clearTimeout(t);
  }, [idx, load]);

  const shown = rows.concat(extra);
  // what the boxes say right now, against what the store was asked
  const draft = { coin, tf, signal, profitable, minTrades, minWinrate, minTp };
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
  const andLine = (f: typeof draft) => [
    f.coin || "all coins",
    f.tf || "all timeframes",
    f.signal || "all signals",
    f.minTrades > 0 ? `min trades = ${f.minTrades}` : "any trades",
    f.minWinrate > 0 ? `min win % = ${f.minWinrate}` : "any win %",
    f.minTp > 0 ? `min TP % = ${f.minTp}` : "any TP",
    f.profitable ? "profit > 0" : "losers included",
  ].join(" AND ");
  // The REQUEST in words — what the spinner is waiting for, not what is on
  // screen (the caption already says that). The SAME sentence the filter line
  // prints, so "AND" means the same thing everywhere on this panel, and it
  // reads `applied` because that is what was actually sent.
  const asking = `${andLine(applied)} — ${desc ? "highest" : "lowest"} `
    + `${STRATEGY_SORTS[sort]} first`;
  // asked for, not served, and nothing in flight — i.e. the request failed
  const missed = !loading && (Object.keys(applied) as (keyof typeof applied)[])
    .some((k) => applied[k] !== servedFilters[k]);
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
        minTp: applied.minTp, desc,
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
          <select className={sel} value={coin} onChange={(e) => setCoin(e.target.value)} aria-label="Coin">
            <option value="">all coins</option>
            {facets.coins.map((c) => <option key={c}>{c}</option>)}
          </select>
          <select className={sel} value={tf} onChange={(e) => setTf(e.target.value)} aria-label="Timeframe">
            <option value="">all timeframes</option>
            {facets.tfs.map((t) => <option key={t}>{t}</option>)}
          </select>
          <select className={sel} value={signal} onChange={(e) => setSignal(e.target.value)} aria-label="Signal">
            <option value="">all signals</option>
            {facets.signals.map((s) => <option key={s}>{s}</option>)}
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
               minTp: applied.minTp, desc })}>
            download all ({total.toLocaleString()}{capped ? "+" : ""}) CSV
          </a>
        </div>
      </div>
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
      {!err && !waiting && !shown.length && (minWinrate > 0 || minTrades > 0 || minTp > 0) && (
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
              {["id", "coin", "tf", "signal", "th%", "SL%", "TP%", "sizing", "lev", "margin $", "PROFIT $", "win %", "trades", "W", "L", "green", "dip $"].map((h) => (
                <TableCell key={h} isHeader
                  onClick={() => {
                    const next = HEAD_SORT[h];
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
                    HEAD_SORT[h] ? "cursor-pointer select-none hover:text-brand-600" : ""} ${
                    h === STRATEGY_SORTS[servedSort]
                      ? "text-brand-600 dark:text-brand-400"
                      : h === STRATEGY_SORTS[sort]
                        ? "text-warning-600 dark:text-warning-400"
                        : "text-gray-500 dark:text-gray-400"}`}
                  title={HEAD_SORT[h] ? `sort every row by ${h}` : undefined}>
                  {h}{h === STRATEGY_SORTS[servedSort] ? (servedDesc ? " ↓" : " ↑")
                     : h === STRATEGY_SORTS[sort] ? " …" : ""}
                </TableCell>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
            {shown.map((r) => (
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
                <TableCell className={`px-3 py-2 text-theme-sm font-semibold ${(r.profit ?? 0) >= 0 ? "text-success-600" : "text-error-500"}`}>{fmtMoney(r.profit)}</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{r.winrate?.toFixed(2)}</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{r.trades}</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm text-success-600">{r.wins}</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm text-error-500">{r.losses}</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{r.green ?? "—"}/{r.months ?? "—"}</TableCell>
                <TableCell className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{r.dd?.toFixed(2) ?? "—"}</TableCell>
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
            </div>
          )}
        </div>
      )}
    </div>
  );
}
