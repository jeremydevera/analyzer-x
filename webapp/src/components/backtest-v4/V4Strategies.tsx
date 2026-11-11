"use client";
/** BACKTEST V4 (operator, Nov 10, 2026: "can you do backtest v4 i want the strategies stored there,
 *  then follow the format like backtest v2 where i can see winrate and filter by day etc").
 *
 *  Every number here is the server's (tradingagents/v4_store.py, /api/v4/*): the filters are sent to
 *  the QUERY - a "last N days" box re-adds every row over that slice of its trades, it never hides
 *  rows of a page the server already cut (CLAUDE.md kit item G). Dollars come back already scaled to
 *  the base margin typed in the box; dates are fmtWhen/fmtWhenMs, never a hand-rolled stamp.
 */
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { API_BASE, fmtWhen } from "@/lib/api";
import PageButtons from "@/components/common/PageButtons";
import { Table, TableBody, TableCell, TableHeader, TableRow } from "@/components/ui/table";

type Row = {
  id: string; coin: string; tf: string; strategy: string; label: string; skill: string;
  tp: number | null; sl: number; leverage: number; trades: number; wins: number; losses: number;
  win_rate: number; profit: number; worst_run: number; worst_run_n: number; dip: number;
  green: number; months_n: number; months: Record<string, number>;
  older_trades: number; older_wins: number; older_profit: number;
  newer_trades: number; newer_wins: number; newer_profit: number; older_lost: boolean;
  start_s: number; split_s: number; end_s: number; days_of_data: number;
  total_trades: number; total_profit: number;
};
type Answer = {
  ready: boolean; why?: string; rows: Row[]; total: number; offset: number; limit: number;
  base_margin: number; leverage: number; notional: number; notes: string[];
  measured?: { strategies: number; trades: number; built_s: number; data_end_s: number;
    sources: Record<string, number>;
    exits?: { minute: number; candle: number; unclear: number; from_s: number } | null };
  window: { days: number | null; from_s: number | null; to_s: number; unseen: boolean } | null;
};
type Trade = { entry_s: number; exit_s: number; side: string; why: string; pnl: number;
  running: number; unseen: boolean };
type Log = { found: boolean; total_profit: number; trades: number; wins: number; losses: number;
  win_rate: number; worst_run: number; worst_run_n: number; dip: number; split_s: number;
  window: { days: number | null; unseen: boolean; from_s: number | null };
  months: Record<string, number>; log: Trade[]; label: string; skill: string };
type Daily = { phase: string; why: string; words: string };
type Facets = { coins: string[]; tfs: string[]; strategies: string[]; skills: string[] };

const PER_PAGE = 50;
const LOG_PER_PAGE = 50;
const th = "px-2 py-2 text-left text-theme-xs font-medium text-gray-500 dark:text-gray-400 whitespace-nowrap";
const td = "whitespace-nowrap px-2 py-2 text-theme-sm tabular-nums text-gray-700 dark:text-gray-300";
const box = "h-9 rounded-lg border border-gray-300 bg-transparent px-2 text-theme-sm text-gray-800 "
  + "dark:border-gray-700 dark:text-white/90";
const lab = "flex flex-col gap-1 text-theme-xs text-gray-500 dark:text-gray-400";

type F = {
  id: string; coin: string; tf: string; strategy: string; skill: string; minWin: string; minTrades: string;
  minProfit: string; minGreen: string; maxDip: string; maxTp: string; maxSl: string; days: string;
  months: string; unseen: boolean; olderOk: boolean; profitable: boolean; tpOverSl: boolean; margin: string;
};
const EMPTY: F = { id: "", coin: "", tf: "", strategy: "", skill: "", minWin: "", minTrades: "", minProfit: "",
  minGreen: "", maxDip: "", maxTp: "", maxSl: "", days: "", months: "", unseen: false, olderOk: false,
  profitable: false, tpOverSl: false, margin: "5" };

function money(v: number): string {
  return `${v >= 0 ? "+" : "−"}$${Math.abs(v).toFixed(2)}`;
}
const tone = (v: number) => (v > 0 ? "text-success-600 dark:text-success-500"
  : v < 0 ? "text-error-600 dark:text-error-500" : "");
const monthName = (k: string) => {
  const [y, m] = k.split("-");
  return `${["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][Number(m) - 1]} ${y}`;
};

function query(f: F, sort: string, desc: boolean, page: number): string {
  const p = new URLSearchParams();
  const set = (k: string, v: string | number | boolean) => { if (v !== "" && v !== false) p.set(k, String(v)); };
  if (f.id.trim()) set("row_id", f.id.trim());
  set("coin", f.coin.trim().toUpperCase()); set("tf", f.tf); set("strategy", f.strategy); set("skill", f.skill);
  set("min_winrate", f.minWin); set("min_trades", f.minTrades); set("min_profit", f.minProfit);
  set("min_green", f.minGreen); set("max_dip", f.maxDip); set("max_tp", f.maxTp); set("max_sl", f.maxSl);
  set("days", f.days); set("months", f.months); set("unseen", f.unseen); set("older_ok", f.olderOk);
  set("profitable", f.profitable); set("tp_over_sl", f.tpOverSl);
  set("base_margin", Number(f.margin) > 0 ? f.margin : "5");
  p.set("sort", sort); p.set("desc", String(desc));
  p.set("limit", String(PER_PAGE)); p.set("offset", String((page - 1) * PER_PAGE));
  return p.toString();
}

/** the active filters, by name, for the row count (what the page is NOT showing) */
function named(f: F): string[] {
  const o: string[] = [];
  if (f.id.trim()) return [`id ${f.id.trim()} (overrides every other filter)`];
  if (f.coin.trim()) o.push(`coin ${f.coin.trim().toUpperCase()}`);
  if (f.tf) o.push(`timeframe ${f.tf}`);
  if (f.strategy) o.push(`strategy ${f.strategy}`);
  if (f.skill) o.push(`skill ${f.skill}`);
  if (f.minWin) o.push(`win rate ≥ ${f.minWin}%`);
  if (f.minTrades) o.push(`≥ ${f.minTrades} trades`);
  if (f.minProfit) o.push(`profit ≥ $${f.minProfit}`);
  if (f.minGreen) o.push(`≥ ${f.minGreen} green months`);
  if (f.maxDip) o.push(`worst dip ≤ $${f.maxDip}`);
  if (f.maxTp) o.push(`TP ≤ ${f.maxTp}%`);
  if (f.maxSl) o.push(`SL ≤ ${f.maxSl}%`);
  if (f.days) o.push(`last ${f.days} days`);
  if (f.months) o.push(`last ${f.months} months`);
  if (f.unseen) o.push("unseen days only");
  if (f.olderOk) o.push("made money on its older days");
  if (f.profitable) o.push("made money");
  if (f.tpOverSl) o.push("TP bigger than SL");
  return o;
}

export default function V4Strategies() {
  const [f, setF] = useState<F>(EMPTY);
  const [sort, setSort] = useState("profit");
  const [desc, setDesc] = useState(true);
  const [page, setPage] = useState(1);
  const [ans, setAns] = useState<Answer | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [facets, setFacets] = useState<Facets | null>(null);
  const [daily, setDaily] = useState<Daily | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [log, setLog] = useState<Log | null>(null);
  const [logErr, setLogErr] = useState<string | null>(null);
  const [logPage, setLogPage] = useState(1);
  const ask = useRef(0);
  const update = (patch: Partial<F>) => { setF((o) => ({ ...o, ...patch })); setPage(1); setOpen(null); };

  useEffect(() => {
    fetch(`${API_BASE}/api/v4/facets`, { cache: "no-store" }).then((r) => r.json()).then(setFacets).catch(() => {});
    // where the daily refresh is (the server only reads it): said under the title
    fetch(`${API_BASE}/api/v4/daily`, { cache: "no-store" }).then((r) => r.json()).then(setDaily).catch(() => {});
  }, []);

  // live typing: every change asks the store again, after a short pause; an old answer never lands
  useEffect(() => {
    const mine = ++ask.current;
    setBusy(true);
    const t = setTimeout(() => {
      fetch(`${API_BASE}/api/v4/strategies?${query(f, sort, desc, page)}`, { cache: "no-store" })
        .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
        .then((d: Answer) => { if (mine === ask.current) { setAns(d); setErr(null); setBusy(false); } })
        .catch((e) => { if (mine === ask.current) { setErr(String(e.message ?? e)); setBusy(false); } });
    }, 350);
    return () => clearTimeout(t);
  }, [f, sort, desc, page]);

  const openLog = useCallback((r: Row) => {
    if (open === r.id) { setOpen(null); return; }
    setOpen(r.id); setLog(null); setLogErr(null); setLogPage(1);
    const p = new URLSearchParams({ row_id: r.id, base_margin: Number(f.margin) > 0 ? f.margin : "5" });
    if (f.days) p.set("days", f.days);
    else if (f.months) p.set("days", String(Math.round(Number(f.months) * 30.4375)));
    if (f.unseen) p.set("unseen", "true");
    fetch(`${API_BASE}/api/v4/strategies/trades?${p}`, { cache: "no-store" })
      .then((x) => { if (!x.ok) throw new Error(`HTTP ${x.status}`); return x.json(); })
      .then(setLog).catch((e) => setLogErr(String(e.message ?? e)));
  }, [open, f.margin, f.days, f.months, f.unseen]);
  // an id typed into the find box opens that row's log by itself (once per new match)
  const opened = useRef("");
  useEffect(() => {
    const r = ans?.rows?.[0];
    if (f.id.trim() && r && ans?.rows.length === 1 && opened.current !== r.id) { opened.current = r.id; openLog(r); }
    if (!f.id.trim()) opened.current = "";
  }, [ans, f.id, openLog]);

  const head = (key: string, label: string, hint?: string) => (
    <TableCell isHeader className={th}>
      <button type="button" title={hint} onClick={() => {
        if (sort === key) setDesc(!desc); else { setSort(key); setDesc(!["id", "coin", "tf", "strategy"].includes(key)); }
        setPage(1);
      }} className="inline-flex items-center gap-1 hover:text-gray-800 dark:hover:text-white">
        {label}{sort === key ? (desc ? " ↓" : " ↑") : ""}
      </button>
    </TableCell>
  );
  const nm = useMemo(() => named(f), [f]);
  const win = ans?.window;
  const total = ans?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PER_PAGE));
  const m = ans?.measured;
  const noop = m && nm.length > 0 && total === m.strategies && !win;

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h3 className="text-lg font-semibold text-gray-800 dark:text-white/90">Backtest v4 — Claude skills’ strategies</h3>
        {/* provenance: the margin and notional are the same on every row, so they live here */}
        <p className="mt-1 text-theme-sm text-gray-500 dark:text-gray-400">
          {m ? `${m.strategies.toLocaleString()} strategies tested (${Object.entries(m.sources).map(([k, v]) => `${v.toLocaleString()} from ${k}`).join(", ")}), ${m.trades.toLocaleString()} trades. ` : ""}
          Each trade is ${ans?.notional?.toLocaleString() ?? "100"} of coin (${ans?.base_margin ?? 5} margin × {ans?.leverage ?? 20}x)
          after the exchange’s 0.075% fee each way and the coin’s usual gap; {m?.exits
            ? `a stop and a target are settled minute by minute since ${fmtWhen(m.exits.from_s)} (${m.exits.minute.toLocaleString()} of ${(m.exits.minute + m.exits.candle).toLocaleString()} candles an open trade lived through; the rest, and every trade before that day, by the candle’s close)`
            : "a stop and a target are checked on the candle’s close"}.
          Each strategy was chosen on the older 70% of its candles and judged on the newest 30% it never saw.
          {m ? ` Candles run to ${fmtWhen(m.data_end_s)}; filed ${fmtWhen(m.built_s)}.` : ""}
        </p>
        {/* the daily refresh, and what the trades do not pay (the rooms that follow this tab say the same) */}
        <p className="mt-1 text-theme-sm text-gray-500 dark:text-gray-400">
          Backtest v4 is refreshed every day
          {daily ? ` — ${daily.words}` : ""}.
          Every trade pays its coin&apos;s usual gap, not its own minute&apos;s order book (100% typical cost).
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-3 rounded-xl border border-gray-200 p-3 dark:border-gray-800">
        <label className={lab}>Find by ID (overrides the rest)
          <input className={`${box} w-36`} value={f.id} placeholder="#LLZM9D" onChange={(e) => update({ id: e.target.value })} />
        </label>
        <label className={lab}>Base margin $
          <input className={`${box} w-20`} inputMode="decimal" value={f.margin} onChange={(e) => update({ margin: e.target.value })} />
        </label>
        <label className={lab}>Coin
          <input className={`${box} w-28`} list="v4coins" value={f.coin} placeholder="BTC" onChange={(e) => update({ coin: e.target.value })} />
          <datalist id="v4coins">{(facets?.coins ?? []).map((c) => <option key={c} value={c} />)}</datalist>
        </label>
        <label className={lab}>Timeframe
          <select className={box} value={f.tf} onChange={(e) => update({ tf: e.target.value })}>
            <option value="">all</option>{(facets?.tfs ?? []).map((t) => <option key={t}>{t}</option>)}
          </select>
        </label>
        <label className={lab}>Strategy
          <select className={box} value={f.strategy} onChange={(e) => update({ strategy: e.target.value })}>
            <option value="">all</option>{(facets?.strategies ?? []).map((t) => <option key={t}>{t}</option>)}
          </select>
        </label>
        <label className={lab}>Skill
          <select className={box} value={f.skill} onChange={(e) => update({ skill: e.target.value })}>
            <option value="">all</option>{(facets?.skills ?? []).map((t) => <option key={t}>{t}</option>)}
          </select>
        </label>
        <label className={lab}>Min win rate %
          <input className={`${box} w-20`} inputMode="decimal" value={f.minWin} onChange={(e) => update({ minWin: e.target.value })} />
        </label>
        <label className={lab}>Min trades
          <input className={`${box} w-20`} inputMode="numeric" value={f.minTrades} onChange={(e) => update({ minTrades: e.target.value })} />
        </label>
        <label className={lab}>Min profit $
          <input className={`${box} w-24`} inputMode="decimal" value={f.minProfit} onChange={(e) => update({ minProfit: e.target.value })} />
        </label>
        <label className={lab}>Min months green (count)
          <input className={`${box} w-24`} inputMode="numeric" value={f.minGreen} onChange={(e) => update({ minGreen: e.target.value })} />
        </label>
        <label className={lab}>Max worst dip $
          <input className={`${box} w-24`} inputMode="decimal" value={f.maxDip} onChange={(e) => update({ maxDip: e.target.value })} />
        </label>
        <label className={lab}>Max TP %
          <input className={`${box} w-20`} inputMode="decimal" value={f.maxTp} onChange={(e) => update({ maxTp: e.target.value })} />
        </label>
        <label className={lab}>Max SL %
          <input className={`${box} w-20`} inputMode="decimal" value={f.maxSl} onChange={(e) => update({ maxSl: e.target.value, })} />
        </label>
        <label className={lab}>Last N days
          <input className={`${box} w-20`} inputMode="numeric" value={f.days} onChange={(e) => update({ days: e.target.value, months: "" })} />
        </label>
        <label className={lab}>Last N months
          <input className={`${box} w-20`} inputMode="numeric" value={f.months} onChange={(e) => update({ months: e.target.value, days: "" })} />
        </label>
        {([["unseen", "Unseen days only (newest 30%)"], ["olderOk", "Made money on its older days"],
          ["profitable", "Made money"], ["tpOverSl", "TP bigger than SL"]] as const).map(([k, t]) => (
          <label key={k} className="flex h-9 items-center gap-2 text-theme-xs text-gray-600 dark:text-gray-300">
            <input type="checkbox" checked={f[k]} onChange={(e) => update({ [k]: e.target.checked } as Partial<F>)} />{t}
          </label>
        ))}
        <button type="button" className="h-9 rounded-lg border border-gray-300 px-3 text-theme-sm text-gray-700 dark:border-gray-700 dark:text-gray-300"
          onClick={() => { setF({ ...EMPTY, margin: f.margin }); setPage(1); setOpen(null); }}>Clear all</button>
      </div>

      {err && <p className="text-theme-sm text-error-600">Could not read the list: {err}</p>}
      {ans && !ans.ready && <p className="text-theme-sm text-gray-500 dark:text-gray-400">{ans.why}</p>}
      {ans?.ready && (
        <>
          <p className="text-theme-sm text-gray-700 dark:text-gray-300" aria-live="polite">
            <b>{total.toLocaleString()}</b> of {m?.strategies.toLocaleString()} strategies
            {nm.length ? <> match {nm.join(" · ")}</> : <> shown, no filter on</>}
            {win?.days && win.from_s ? <> — each re-added over the trades that closed {fmtWhen(win.from_s)} to {fmtWhen(win.to_s)}</> : null}
            {win?.unseen ? <> — only trades opened after each strategy’s split</> : null}
            {busy ? " …" : ""}
            {noop ? <span className="text-gray-500"> (these filters cut nothing: every strategy passes them)</span> : null}
          </p>
          {ans.notes.map((n) => <p key={n} className="text-theme-xs text-gray-500 dark:text-gray-400">{n}</p>)}
          <div className="overflow-x-auto rounded-xl border border-gray-200 dark:border-gray-800">
            <Table>
              <TableHeader>
                <TableRow>
                  {head("id", "ID")}{head("coin", "Coin")}{head("tf", "TF")}{head("strategy", "Strategy")}
                  {head("profit", win?.days ? "PROFIT / TOTAL $ (window)" : win?.unseen ? "PROFIT / TOTAL $ (unseen)" : "PROFIT / TOTAL $")}
                  {head("tp", "TP %")}{head("sl", "SL %")}
                  <TableCell isHeader className={th}>Lev</TableCell>
                  {head("wins", "Wins")}{head("losses", "Losses")}{head("winrate", "Win rate")}
                  {head("worst_run", "Worst losing run", "the sum of the worst unbroken run of losses, and how many trades it was")}
                  {head("dip", "Worst dip")}{head("trades", "Trades")}{head("green", "Months green")}
                </TableRow>
              </TableHeader>
              <TableBody>
                {ans.rows.map((r) => (
                  <Fragment key={r.id}>
                    <TableRow className="cursor-pointer hover:bg-gray-50 dark:hover:bg-white/[0.03]" onClick={() => openLog(r)}>
                      <TableCell className={td}><span className="font-mono">#{r.id}</span></TableCell>
                      <TableCell className={td}>{r.coin}</TableCell>
                      <TableCell className={td}>{r.tf}</TableCell>
                      <TableCell className={`${td} max-w-[22rem] truncate`} title={r.label}>{r.label}</TableCell>
                      <TableCell className={`${td} font-semibold ${tone(r.profit)}`}>{money(r.profit)}</TableCell>
                      <TableCell className={td}>{r.tp == null ? "none" : `${r.tp}%`}</TableCell>
                      <TableCell className={td}>{r.sl}%</TableCell>
                      <TableCell className={td}>{r.leverage}x</TableCell>
                      <TableCell className={td}>{r.wins}</TableCell>
                      <TableCell className={td}>{r.losses}</TableCell>
                      <TableCell className={td}>{r.trades ? `${r.win_rate.toFixed(1)}%` : "—"}</TableCell>
                      <TableCell className={td}>{r.worst_run_n ? `${money(r.worst_run)} over ${r.worst_run_n}` : "—"}</TableCell>
                      <TableCell className={td}>{r.dip ? `$${r.dip.toFixed(2)}` : "—"}</TableCell>
                      <TableCell className={td}>{r.trades}</TableCell>
                      <TableCell className={td}>{r.green}/{r.months_n}</TableCell>
                    </TableRow>
                    {open === r.id && (
                      <TableRow>
                        <TableCell colSpan={15} className="bg-gray-50 px-4 py-3 dark:bg-white/[0.02]">
                          <Detail r={r} log={log} err={logErr} page={logPage} setPage={setLogPage} margin={ans.base_margin} notional={ans.notional} />
                        </TableCell>
                      </TableRow>
                    )}
                  </Fragment>
                ))}
              </TableBody>
            </Table>
          </div>
          {ans.rows.length === 0 && (
            <p className="text-theme-sm text-gray-500 dark:text-gray-400">
              Nothing matches. This was asked of all {m?.strategies.toLocaleString()} strategies in the store, so it is the filters, not the page.
            </p>
          )}
          <PageButtons cur={page} pages={pages} goto={setPage} what="strategies" busy={busy} />
        </>
      )}
    </div>
  );
}

function Detail({ r, log, err, page, setPage, margin, notional }: {
  r: Row; log: Log | null; err: string | null; page: number; setPage: (n: number) => void;
  margin: number; notional: number;
}) {
  if (err) return <p className="text-theme-sm text-error-600">Could not read the trades: {err}</p>;
  if (!log) return <p className="text-theme-sm text-gray-500">Reading the trades…</p>;
  const shown = log.log.slice((page - 1) * LOG_PER_PAGE, page * LOG_PER_PAGE);
  const pages = Math.max(1, Math.ceil(log.log.length / LOG_PER_PAGE));
  // the grid scrolls sideways, so the panel is a fixed-width block pinned to the left edge: its text
  // wraps inside the visible part instead of running off the right of the table
  return (
    <div className="sticky left-0 flex w-[64rem] max-w-[calc(100vw-22rem)] flex-col gap-3 whitespace-normal">
      <p className="text-theme-sm text-gray-700 dark:text-gray-300">
        <b>#{r.id}</b> {r.coin} {r.tf} — {log.label} <span className="text-gray-500">({log.skill})</span>.{" "}
        ${margin} margin × {r.leverage}x = ${notional} a trade. Candles {fmtWhen(r.start_s)} to {fmtWhen(r.end_s)};
        chosen on the older days up to {fmtWhen(r.split_s)}: {r.older_trades} trades, {money(r.older_profit)}
        {r.older_lost ? " (it LOST there — shown anyway)" : ""}; unseen days: {r.newer_trades} trades, {money(r.newer_profit)}.
        {log.window.days && log.window.from_s ? ` This list: only trades closed after ${fmtWhen(log.window.from_s)}.` : ""}
        {log.window.unseen ? " This list: only trades opened after the split." : ""}
      </p>
      <p className="text-theme-md font-semibold text-gray-800 dark:text-white/90">
        TOTAL PROFIT <span className={tone(log.total_profit)}>{money(log.total_profit)}</span>{" "}
        <span className="text-theme-sm font-normal text-gray-600 dark:text-gray-300">
          over {log.trades} trades: {log.wins} won, {log.losses} lost ({log.trades ? log.win_rate.toFixed(1) : "0"}%);
          worst losing run {log.worst_run_n ? `${money(log.worst_run)} over ${log.worst_run_n}` : "none"};
          worst dip ${log.dip.toFixed(2)}
        </span>
      </p>
      <p className="text-theme-xs text-gray-500 dark:text-gray-400">
        By month (closed in it): {Object.entries(log.months).map(([k, v]) => `${monthName(k)} ${money(v)}`).join(" · ") || "no trade"}
      </p>
      <div className="overflow-x-auto">
        <table className="min-w-full text-theme-xs tabular-nums text-gray-700 dark:text-gray-300">
          <thead>
            <tr className="text-left text-gray-500"><th className="px-2 py-1">#</th><th className="px-2 py-1">Opened</th>
              <th className="px-2 py-1">Closed</th><th className="px-2 py-1">Side</th><th className="px-2 py-1">Out by</th>
              <th className="px-2 py-1">Profit</th><th className="px-2 py-1">Running</th><th className="px-2 py-1">Seen?</th></tr>
          </thead>
          <tbody>
            {shown.map((t, i) => (
              <tr key={`${t.entry_s}-${t.exit_s}`}>
                <td className="px-2 py-1">{(page - 1) * LOG_PER_PAGE + i + 1}</td>
                <td className="whitespace-nowrap px-2 py-1">{fmtWhen(t.entry_s)}</td>
                <td className="whitespace-nowrap px-2 py-1">{fmtWhen(t.exit_s)}</td>
                <td className="px-2 py-1">{t.side}</td><td className="px-2 py-1">{t.why}</td>
                <td className={`px-2 py-1 ${tone(t.pnl)}`}>{money(t.pnl)}</td>
                <td className={`px-2 py-1 ${tone(t.running)}`}>{money(t.running)}</td>
                <td className="px-2 py-1">{t.unseen ? "unseen" : "chosen on"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <PageButtons cur={page} pages={pages} goto={setPage} what="trades" />
    </div>
  );
}
