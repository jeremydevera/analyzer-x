"use client";
/** BACKTEST V3 — one coin and one idea, run the v3 way on request.
 *
 * Operator, Oct 23, 2026: *"i dont see it in ui where is it i said to create
 * backtest v3 tab"*, then *"Tab now, fill it later"*. The run is the server's
 * (`POST /api/v3/run`, tradingagents/v3_page.py, the same walk as
 * `python -m tradingagents.v3_smoke`): waiting orders that fill only when the
 * price trades through them (post-only — one that would fill at once is
 * cancelled), the idea's own exit, the risk box's dollars lost when a stop is
 * hit, and every cost. Every figure below is read from that answer — the
 * profit is the sum of the trade rows as shown, never a number worked out
 * here. The tested-ideas section says what the server says it can say.
 *
 * Oct 27, 2026 (operator: "go" to "both"): the idea box lists the four v3
 * families first, under "New v3 ideas". A family runs with its own
 * timeframes, settings and filters and closes by its OWN exit (no exit boxes:
 * the server says it in words), over the plan's universe — a look at one idea
 * on one coin, never the proof. Below, the 3-coin check's verdicts
 * (`V3Check`), labelled a check.
 */
import { useEffect, useMemo, useState } from "react";
import { API_BASE, fmtWhenMs } from "@/lib/api";
import { useVenueName } from "@/lib/venue";
import PageButtons from "@/components/common/PageButtons";
import V3Check, { type Check } from "@/components/backtest-v3/V3Check";
import { Table, TableBody, TableCell, TableHeader, TableRow } from "@/components/ui/table";

type Field = { key: string; label: string; default: number; min: number; max: number; whole?: boolean };
type Options = {
  venue: string; coins: string[]; coins_error: string; tfs: string[]; signals: string[];
  thresh_signals: string[]; days: number[]; default_days: number;
  exits: Record<string, { label: string; fields: Field[] }>;
  risk: { default: number; min: number; max: number };
  defaults: { sym: string; tf: string; signal: string; exit: string };
  families: Family[];
  plan: { id: string; start_ms: number; end_ms: number; last_month: string } | null;
  plan_error: string;
  tested: { state: string; rows: number | null; words: string; store: Omit<NonNullable<Check>, "state"> | null; check: Check };
};
type Family = {
  name: string; words: string; tfs: string[]; long: string[]; short: string[];
  settings: { key: string; value: number; words: string;
    exit: Record<string, { target: string; stop: string }> }[];
  filters: Record<string, { key: string; words: string }[]>;
  not_tried: Record<string, { key: string; why: string }[]>;
};
type Trade = {
  n: number; side: string; signal_ms: number; entry_ms: number; entry: number; exit_ms: number;
  exit: number; why: string; how: string; contracts: number; notional: number; leverage: number;
  margin: number; fee_in: number; fee_out: number; gap_out: number; funding: number; pnl: number;
  total: number; measured_exit: boolean; funding_estimated: boolean;
};
type Missed = {
  signal_ms: number; side: string; limit: number; why: string; how: string;
  market: { refused?: string; entry?: number; entry_ms?: number; exit?: number; exit_ms?: number;
    why?: string; how?: string; pnl?: number };
};
type Result = {
  id: string;
  provenance: {
    sym: string; tf: string; signal: string; th_pct: number | null; exit: string; exit_words: string;
    params: Record<string, number>; days: number; start_ms: number; end_ms: number; venue: string;
    risk_usd: number; maker_fee: number; taker_fee: number; flat_slip: number; coverage: number;
    candles: number; points: number;
    // a v3 family's run only
    family?: string; setting?: string; setting_words?: string; family_words?: string;
    filter?: string; filter_words?: string; target?: string; stop?: string;
    flat_slip_source?: string; universe?: string[]; plan_id?: string; plan_end_ms?: number;
    look?: string;
  };
  summary: {
    trades: number; wins: number; losses: number; win_rate: number | null; break_even: number | null;
    profit: number; worst_run_usd: number; worst_run_trades: number; leverage_min: number | null;
    leverage_max: number | null; notional_min: number | null; notional_max: number | null;
    not_filled: number; post_only_reject: number; refused: number; missed_entered: number;
    missed_pnl: number; open_at_end: number; counts: Record<string, number>; combos: number;
    trades_per_day: number | null;
    filter?: Record<string, number>; filter_words?: string;
  };
  trades: Trade[]; missed: Missed[]; elapsed_s: number;
};

const PER_PAGE = 10;           // Auto Trade's own page size (forecast_v2_api.PER_PAGE)
const card = "overflow-hidden rounded-2xl border border-gray-200 bg-white p-5 "
  + "dark:border-white/[0.05] dark:bg-white/[0.03]";
const sel = "h-10 w-full rounded-lg border border-gray-300 bg-transparent px-3 text-theme-sm "
  + "text-gray-700 focus:outline-hidden focus:ring-2 focus:ring-brand-500/20 "
  + "dark:border-gray-700 dark:bg-gray-900 dark:text-gray-300";
const lab = "mb-1 block text-theme-xs text-gray-500 dark:text-gray-400";
const th = "px-3 py-2 text-left text-theme-xs font-medium text-gray-500 dark:text-gray-400";
// one line per row: a date that wraps onto three lines made every trade three
// rows tall; the table scrolls sideways inside its box instead
const td = "whitespace-nowrap px-3 py-2 text-theme-sm tabular-nums text-gray-700 dark:text-gray-300";

// what each count means, in plain words (v3_engine.COUNT_KEYS)
const COUNT_WORDS: Record<string, string> = {
  missed: "orders the price never traded through",
  post_only_reject: "orders cancelled because they would have filled at once",
  placement_unmeasured: "orders placed with no recorded order book of that minute",
  unsafe_stop: "signals whose stop no leverage keeps safe",
  too_small: "signals too small for one lot at this risk",
  no_levels: "signals the exit rule could not set up yet",
  gate_blocked: "signals the cost check refused",
  chase_skip: "signals where the price had run away",
  closed_skip: "signals on a closed stock market",
  cost_unmeasured: "exits that paid a typical gap (no recorded book)",
  funding_estimated: "holds charged an estimated funding rate",
  settled_by_candle: "exits decided by the candle (minutes missing)",
  fill_by_candle: "fill decisions made by the candle (minutes missing)",
  unclear: "candles that reached the stop and the target (booked as the stop)",
  no_next_bar: "signals on the last candle (no time to fill)",
  partial_points: "candles walked with some minutes missing",
  no_points: "candles walked with no minutes at all",
};

function money(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(2)}`;
}
function plain(v: number | null | undefined): string {
  return v == null || !Number.isFinite(v) ? "—" : v.toFixed(2);
}
function price(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const a = Math.abs(v);
  return v.toFixed(a >= 1000 ? 2 : a >= 1 ? 4 : 6);
}
function pct(v: number | null | undefined, digits = 1): string {
  return v == null || !Number.isFinite(v) ? "—" : `${(v * 100).toFixed(digits)}%`;
}
const tone = (v: number) => (v >= 0 ? "text-success-600 dark:text-success-400" : "text-error-600 dark:text-error-400");

type SortKey = keyof Trade;

export default function V3Runner() {
  const venue = useVenueName();
  const [opts, setOpts] = useState<Options | null>(null);
  const [optErr, setOptErr] = useState("");
  const [sym, setSym] = useState("");
  const [tf, setTf] = useState("");
  const [signal, setSignal] = useState("");
  const [exit, setExit] = useState("");
  const [params, setParams] = useState<Record<string, string>>({});
  const [days, setDays] = useState(30);
  const [risk, setRisk] = useState("1");
  const [thPct, setThPct] = useState("");
  const [setting, setSetting] = useState("");
  const [filter, setFilter] = useState("none");
  const [running, setRunning] = useState(false);
  const [res, setRes] = useState<Result | null>(null);
  const [runErr, setRunErr] = useState("");
  const [page, setPage] = useState(1);
  const [missedPage, setMissedPage] = useState(1);
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "n", dir: 1 });

  useEffect(() => {
    fetch(`${API_BASE}/api/v3/options`, { cache: "no-store" })
      .then(async (r) => {
        if (!r.ok) throw new Error(`/api/v3/options -> HTTP ${r.status}`);
        return (await r.json()) as Options;
      })
      .then((o) => {
        setOpts(o);
        setOptErr("");
        setSym(o.defaults.sym);
        setTf(o.defaults.tf);
        setSignal(o.defaults.signal);
        setExit(o.defaults.exit);
        setDays(o.default_days);
        setRisk(String(o.risk.default));
      })
      .catch((e) => setOptErr(String(e?.message ?? e)));
  }, []);

  const fam = opts?.families.find((f) => f.name === signal) ?? null;
  const fields = !fam && opts && exit ? opts.exits[exit]?.fields ?? [] : [];
  const tfChoices = fam ? fam.tfs : opts?.tfs ?? [];
  const famSetting = fam ? fam.settings.find((x) => x.key === setting) ?? fam.settings[0] : null;
  const famFilters = useMemo(() => (fam ? fam.filters[tf] ?? [] : []), [fam, tf]);
  const famExit = fam && famSetting ? famSetting.exit[tf] ?? null : null;
  const notTried = fam ? fam.not_tried[tf] ?? [] : [];
  // picking an idea keeps the other boxes on choices that idea has
  const pickIdea = (name: string) => {
    setSignal(name);
    const f = opts?.families.find((x) => x.name === name);
    if (f) {
      if (!f.tfs.includes(tf)) setTf(f.tfs[0]);
      if (!f.settings.some((x) => x.key === setting)) setSetting(f.settings[0].key);
    } else if (opts && !opts.tfs.includes(tf)) {
      setTf(opts.defaults.tf);
    }
  };
  // a timeframe a filter is not tried on (funding_minutes on 1d) falls back to no filter
  const filterNow = famFilters.some((x) => x.key === filter) ? filter : "none";
  const val = (f: Field) => params[`${exit}.${f.key}`] ?? String(f.default);
  const needsTh = !!opts && opts.thresh_signals.includes(signal);

  const runIt = () => {
    if (!opts) return;
    setRunning(true);
    setRunErr("");
    const body = fam
      ? { sym: sym.trim().toUpperCase(), tf, signal: fam.name, setting: famSetting?.key,
          filter: filterNow, days, risk_usd: Number(risk) }
      : {
        sym: sym.trim().toUpperCase(), tf, signal: signal.trim(), exit, days,
        risk_usd: Number(risk),
        params: Object.fromEntries(fields.map((f) => [f.key, Number(val(f))])),
        ...(needsTh && thPct.trim() ? { th_pct: Number(thPct) } : {}),
      };
    fetch(`${API_BASE}/api/v3/run`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    })
      .then(async (r) => {
        const j = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(j?.detail ? String(j.detail) : `/api/v3/run -> HTTP ${r.status}`);
        return j as Result;
      })
      .then((x) => { setRes(x); setPage(1); setMissedPage(1); setSort({ key: "n", dir: 1 }); })
      .catch((e) => setRunErr(String(e?.message ?? e)))
      .finally(() => setRunning(false));
  };

  const sorted = useMemo(() => {
    const rows = [...(res?.trades ?? [])];
    const { key, dir } = sort;
    rows.sort((a, b) => {
      const x = a[key], y = b[key];
      if (typeof x === "number" && typeof y === "number") return (x - y) * dir;
      return String(x).localeCompare(String(y)) * dir;
    });
    return rows;
  }, [res, sort]);
  const pages = Math.max(1, Math.ceil(sorted.length / PER_PAGE));
  const shown = sorted.slice((page - 1) * PER_PAGE, page * PER_PAGE);
  const missed = res?.missed ?? [];
  const missedPages = Math.max(1, Math.ceil(missed.length / PER_PAGE));
  const missedShown = missed.slice((missedPage - 1) * PER_PAGE, missedPage * PER_PAGE);

  const sortBy = (key: SortKey) =>
    setSort((s) => ({ key, dir: s.key === key ? (s.dir === 1 ? -1 : 1) : 1 }));
  const head = (key: SortKey, label: string) => (
    <TableCell isHeader className={`${th} cursor-pointer select-none`} onClick={() => sortBy(key)}
      title="Click to sort">
      {label}{sort.key === key ? (sort.dir === 1 ? " ▲" : " ▼") : ""}
    </TableCell>
  );

  const p = res?.provenance;
  const s = res?.summary;
  const tpWords = p ? (p.exit === "family" ? p.target ?? "—" : p.exit === "fixed" ? `${p.params.tp_pct}%`
    : p.exit === "snap" ? "the 20-candle average" : "none (the trail decides)") : "";
  const slWords = p ? (p.exit === "family" ? p.stop ?? "—" : p.exit === "fixed" ? `${p.params.sl_pct}%`
    : p.exit === "trail" ? `${p.params.atr_mult} x ATR, trailing`
    : `${p.params.stop_atr} x ATR, then ${p.params.max_bars} candles`) : "";
  const counted = s ? Object.entries(s.counts).filter(([, v]) => v > 0) : [];
  // a run with no trade has no leverage: say so, never "—x"
  const levRange = s && s.leverage_min != null
    ? `${s.leverage_min}${s.leverage_max !== s.leverage_min ? `–${s.leverage_max}` : ""}x` : "";
  const levWords = levRange ? `leverage ${levRange}` : "no leverage (no trade)";

  return (
    <div className="flex flex-col gap-5">
      <div className={card}>
        <h3 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">Backtest v3</h3>
        <p className="mt-1 max-w-3xl text-theme-xs text-gray-500 dark:text-gray-400">
          Run one coin and one idea the v3 way on {venue}&apos;s own data: the order waits at the
          signal&apos;s price and fills only when the price trades through it (an order that would fill
          at once is cancelled, so it always pays the lower fee); each idea closes by its own rule;
          every trade risks the dollars in the risk box if its stop is hit; and every trade pays every
          cost. Nothing here places an order or saves anything.
        </p>

        {optErr && <p className="mt-4 text-theme-xs text-error-600 dark:text-error-400">Could not read the choices: {optErr}</p>}
        {!opts && !optErr && <p className="mt-4 text-theme-xs text-gray-500 dark:text-gray-400">Loading the choices...</p>}
        {opts && (
          <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <label className="block">
              <span className={lab}>Coin ({opts.coins.length} on {venue})</span>
              <input className={sel} value={sym} list="v3-coins" aria-label="Coin"
                onChange={(e) => setSym(e.target.value)} />
              <datalist id="v3-coins">{opts.coins.map((c) => <option key={c} value={c} />)}</datalist>
              {opts.coins_error && <span className="mt-1 block text-theme-xs text-error-600">Coin list not read: {opts.coins_error}</span>}
            </label>
            <label className="block">
              <span className={lab}>Timeframe</span>
              <select className={sel} value={tf} aria-label="Timeframe" onChange={(e) => setTf(e.target.value)}>
                {tfChoices.map((x) => <option key={x} value={x}>{x}</option>)}
              </select>
            </label>
            <label className="block">
              <span className={lab}>Idea ({opts.families.length} new v3 ideas, {opts.signals.length} stored)</span>
              <select className={sel} value={signal} aria-label="Idea" onChange={(e) => pickIdea(e.target.value)}>
                <optgroup label="New v3 ideas">
                  {opts.families.map((f) => <option key={f.name} value={f.name}>{f.name}</option>)}
                </optgroup>
                <optgroup label={`Stored ideas (${opts.signals.length})`}>
                  {opts.signals.map((x) => <option key={x} value={x}>{x}</option>)}
                </optgroup>
              </select>
            </label>
            <label className="block">
              <span className={lab}>Window</span>
              <select className={sel} value={days} aria-label="Window" onChange={(e) => setDays(Number(e.target.value))}>
                {opts.days.map((d) => <option key={d} value={d}>past {d} days</option>)}
              </select>
            </label>
            {fam ? (
              <>
                <label className="block">
                  <span className={lab}>Setting</span>
                  <select className={sel} value={famSetting?.key ?? ""} aria-label="Setting"
                    onChange={(e) => setSetting(e.target.value)}>
                    {fam.settings.map((x) => <option key={x.key} value={x.key}>{x.words}</option>)}
                  </select>
                </label>
                <label className="block">
                  <span className={lab}>Filter</span>
                  <select className={sel} value={filterNow} aria-label="Filter" onChange={(e) => setFilter(e.target.value)}>
                    {famFilters.map((x) => <option key={x.key} value={x.key}>{x.key}: {x.words}</option>)}
                  </select>
                </label>
              </>
            ) : (
              <label className="block">
                <span className={lab}>How it closes</span>
                <select className={sel} value={exit} aria-label="How it closes" onChange={(e) => setExit(e.target.value)}>
                  {Object.entries(opts.exits).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
                </select>
              </label>
            )}
            {fields.map((f) => (
              <label key={`${exit}.${f.key}`} className="block">
                <span className={lab}>{f.label}</span>
                <input className={sel} type="number" step="any" min={f.min} max={f.max}
                  value={val(f)} aria-label={f.label}
                  onChange={(e) => setParams((x) => ({ ...x, [`${exit}.${f.key}`]: e.target.value }))} />
              </label>
            ))}
            {!fam && needsTh && (
              <label className="block">
                <span className={lab}>Threshold % (empty = 0.3%)</span>
                <input className={sel} type="number" step="any" value={thPct} aria-label="Threshold %"
                  onChange={(e) => setThPct(e.target.value)} />
              </label>
            )}
            <label className="block">
              <span className={lab}>Risk per trade $ (lost if the stop is hit)</span>
              <input className={sel} type="number" step="any" min={opts.risk.min} max={opts.risk.max}
                value={risk} aria-label="Risk per trade $" onChange={(e) => setRisk(e.target.value)} />
            </label>
            <div className="flex items-end">
              <button type="button" onClick={runIt} disabled={running}
                className="h-10 w-full rounded-lg bg-brand-500 px-4 text-theme-sm font-medium text-white hover:bg-brand-600 disabled:opacity-50">
                {running ? "Running..." : "Run"}
              </button>
            </div>
          </div>
        )}
        {opts && fam && (
          <div className="mt-3 max-w-3xl text-theme-xs text-gray-500 dark:text-gray-400">
            <p>{fam.words}. It closes by its own rule, so there is no exit to pick
              {famExit ? <> — target: {famExit.target}; stop: {famExit.stop}.</> : "."}</p>
            <p className="mt-1">
              It trades only where the universe plan lets this coin ({fam.long.length ? `longs: ${fam.long.join(" or ")}` : "no longs"};
              {" "}{fam.short.length ? `shorts: ${fam.short.join(" or ")}` : "no shorts"}).
              {opts.plan ? <> The plan ends {fmtWhenMs(opts.plan.end_ms)}; after it, {opts.plan.last_month}&apos;s membership stands in.</>
                : <> The plan could not be read: {opts.plan_error}</>}
              {notTried.length > 0 && <> Not tried on {tf}: {notTried.map((x) => `${x.key} (${x.why})`).join("; ")}.</>}
            </p>
            <p className="mt-1">A look at one idea on one coin: one walk over the window, no unseen days and no random runs, so never the proof.</p>
          </div>
        )}
        {running && (
          <p className="mt-3 text-theme-xs text-gray-500 dark:text-gray-400">
            Reading {sym.trim().toUpperCase()}&apos;s candles, minutes, order books and funding from {venue}
            {" "}and walking every signal — from about 10 seconds to a minute for 30 days (the first
            {" "}run after the site starts is the slow one), longer for bigger windows.
          </p>
        )}
        {runErr && <p className="mt-3 text-theme-xs text-error-600 dark:text-error-400">The run was refused: {runErr}</p>}
        {opts && (
          <p className="mt-3 text-theme-xs text-gray-500 dark:text-gray-400">
            The risk box changes the dollars only after you press Run again: sizes round to whole lots,
            so dollars do not scale exactly with it.
          </p>
        )}
      </div>

      {res && p && s && (
        <div className={card}>
          <p className="text-theme-xs text-gray-500 dark:text-gray-400">
            {p.sym} {p.tf} · idea {p.signal}{p.setting_words ? ` ${p.setting_words}` : ""}{p.th_pct != null ? ` at ${p.th_pct}%` : ""}
            {p.filter ? ` · filter ${p.filter} (${p.filter_words})` : ""} · closes by {p.exit_words}
            {" "}· {fmtWhenMs(p.start_ms)} to {fmtWhenMs(p.end_ms)} ({p.candles} candles) on {p.venue}&apos;s data
            {" "}· ${plain(p.risk_usd)} risk a trade · {levWords}
            {" "}· {s.notional_min == null ? "no coin bought (no trade)"
              : `$${plain(s.notional_min)}${s.notional_max !== s.notional_min ? `–$${plain(s.notional_max)}` : ""} of coin a trade`}
            {" "}· fees: {pct(p.maker_fee, 3)} on the waiting order, {pct(p.taker_fee, 3)} plus the gap on a market exit
            {" "}· {pct(p.coverage)} of the minutes had a recorded order book (the rest paid a typical {pct(p.flat_slip, 4)} gap{p.flat_slip_source ? `: ${p.flat_slip_source}` : ""})
            {" "}· margin = the coin bought ÷ its leverage
            {" "}· {s.combos} combination tested · took {res.elapsed_s}s
          </p>
          {p.universe && (
            <p className="mt-1 text-theme-xs text-gray-500 dark:text-gray-400">
              {p.universe.join(" · ")}{p.plan_id ? ` · plan ${p.plan_id}` : ""}
            </p>
          )}
          {p.look && <p className="mt-1 text-theme-xs font-medium text-warning-600 dark:text-warning-400">{p.look}</p>}

          <div className="mt-3 overflow-x-auto">
            <Table>
              <TableHeader className="border-b border-gray-100 dark:border-white/[0.05]">
                <TableRow>
                  {["ID", "Trades", "Trades a day", "Won / lost", "Win rate", "Needs to win", "PROFIT (total $)", "TP", "SL",
                    "Leverage", "Worst losing run", "Not filled", "Cancelled (post-only)",
                    "If bought at the market"].map((h) => (
                    <TableCell key={h} isHeader className={th}>{h}</TableCell>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow>
                  <TableCell className={`${td} font-medium`}>#{res.id}</TableCell>
                  <TableCell className={td}>{s.trades}{s.open_at_end ? ` (${s.open_at_end} still open)` : ""}</TableCell>
                  <TableCell className={td}>{s.trades_per_day != null ? s.trades_per_day.toFixed(2) : "—"}</TableCell>
                  <TableCell className={td}>{s.wins} / {s.losses}</TableCell>
                  <TableCell className={td}>{pct(s.win_rate)}</TableCell>
                  <TableCell className={td} title="the win rate at which this run's average win pays its average loss">{pct(s.break_even)}</TableCell>
                  <TableCell className={`${td} font-semibold ${tone(s.profit)}`}>{money(s.profit)}</TableCell>
                  <TableCell className={td}>{tpWords}</TableCell>
                  <TableCell className={td}>{slWords}</TableCell>
                  <TableCell className={td}>{s.leverage_min == null ? "no trade" : levRange}</TableCell>
                  <TableCell className={`${td} ${s.worst_run_trades ? tone(s.worst_run_usd) : ""}`}>
                    {s.worst_run_trades ? `${money(s.worst_run_usd)} over ${s.worst_run_trades} trades` : "no losses"}
                  </TableCell>
                  <TableCell className={td}>{s.not_filled}</TableCell>
                  <TableCell className={td}>{s.post_only_reject}</TableCell>
                  <TableCell className={`${td} ${tone(s.missed_pnl)}`}>
                    {s.missed_entered ? `${money(s.missed_pnl)} on ${s.missed_entered}` : "—"}
                  </TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </div>

          <h4 className="mt-5 text-theme-sm font-semibold text-gray-800 dark:text-white/90">
            Every trade ({s.trades})
          </h4>
          {s.trades === 0 ? (
            <p className="mt-2 text-theme-xs text-gray-500 dark:text-gray-400">
              No trade in these {p.days} days: {s.not_filled + s.post_only_reject} orders were placed and none filled,
              and {s.refused} signals were refused before an order was placed (see the counts below).
            </p>
          ) : (
            <>
              <div className="mt-2 overflow-x-auto">
                <Table>
                  <TableHeader className="border-b border-gray-100 dark:border-white/[0.05]">
                    <TableRow>
                      {head("n", "#")}{head("side", "Side")}{head("signal_ms", "Signal candle")}
                      {head("entry_ms", "Filled")}{head("entry", "Fill price")}{head("exit_ms", "Closed")}
                      {head("exit", "Close price")}{head("how", "How it closed")}{head("notional", "Size $")}
                      {head("leverage", "Leverage")}{head("margin", "Margin $")}{head("fee_out", "Fees in + out")}
                      {head("gap_out", "Gap out")}{head("funding", "Funding")}{head("pnl", "Profit")}{head("total", "Running total")}
                    </TableRow>
                  </TableHeader>
                  <TableBody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
                    {shown.map((r) => (
                      <TableRow key={r.n}>
                        <TableCell className={td}>{r.n}</TableCell>
                        <TableCell className={td}>{r.side}</TableCell>
                        <TableCell className={td}>{fmtWhenMs(r.signal_ms)}</TableCell>
                        <TableCell className={td}>{fmtWhenMs(r.entry_ms)}</TableCell>
                        <TableCell className={td}>{price(r.entry)}</TableCell>
                        <TableCell className={td}>{fmtWhenMs(r.exit_ms)}</TableCell>
                        <TableCell className={td}>{price(r.exit)}</TableCell>
                        <TableCell className={td}>{r.how}</TableCell>
                        <TableCell className={td}>{plain(r.notional)}</TableCell>
                        <TableCell className={td}>{r.leverage}x</TableCell>
                        <TableCell className={td}>{plain(r.margin)}</TableCell>
                        <TableCell className={td}>{(r.fee_in + r.fee_out).toFixed(3)}</TableCell>
                        <TableCell className={td} title={r.measured_exit ? "the exit minute's recorded book" : "no recorded book: a typical gap"}>
                          {r.gap_out.toFixed(3)}{r.measured_exit ? "" : " *"}
                        </TableCell>
                        <TableCell className={td} title={r.funding_estimated ? "estimated: part of the hold is outside the funding history" : "every settlement in the hold"}>
                          {r.funding >= 0 ? "+" : "−"}{Math.abs(r.funding).toFixed(3)}{r.funding_estimated ? " *" : ""}
                        </TableCell>
                        <TableCell className={`${td} font-medium ${tone(r.pnl)}`}>{money(r.pnl)}</TableCell>
                        <TableCell className={`${td} ${tone(r.total)}`}>{money(r.total)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
              <PageButtons cur={page} pages={pages} goto={setPage} what="Trades" />
              <p className={`mt-3 text-theme-sm font-semibold ${tone(s.profit)}`}>
                TOTAL PROFIT {money(s.profit)} over {s.trades} trades ({s.wins} won, {s.losses} lost)
              </p>
              <p className="mt-1 text-theme-xs text-gray-500 dark:text-gray-400">
                * a typical cost stood in where nothing was recorded. Fees and gaps are dollars on that
                trade&apos;s size; funding is what the hold paid (−) or received (+).
              </p>
            </>
          )}

          {missed.length > 0 && (
            <>
              <h4 className="mt-5 text-theme-sm font-semibold text-gray-800 dark:text-white/90">
                Orders that never filled ({missed.length})
              </h4>
              <div className="mt-2 overflow-x-auto">
                <Table>
                  <TableHeader className="border-b border-gray-100 dark:border-white/[0.05]">
                    <TableRow>
                      {["Signal candle", "Side", "Waiting at", "Why it did not fill", "Bought at the market instead"].map((h) => (
                        <TableCell key={h} isHeader className={th}>{h}</TableCell>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
                    {missedShown.map((m) => (
                      <TableRow key={`${m.signal_ms}-${m.side}`}>
                        <TableCell className={td}>{fmtWhenMs(m.signal_ms)}</TableCell>
                        <TableCell className={td}>{m.side}</TableCell>
                        <TableCell className={td}>{price(m.limit)}</TableCell>
                        <TableCell className={td}>{m.how}</TableCell>
                        <TableCell className={`${td} ${m.market.pnl != null ? tone(m.market.pnl) : ""}`}>
                          {m.market.pnl != null
                            ? `${money(m.market.pnl)} (${m.market.how}, closed ${fmtWhenMs(m.market.exit_ms)})`
                            : `not entered either: ${m.market.refused}`}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
              <PageButtons cur={missedPage} pages={missedPages} goto={setMissedPage} what="Orders that never filled" />
            </>
          )}

          <h4 className="mt-5 text-theme-sm font-semibold text-gray-800 dark:text-white/90">Everything the run counted</h4>
          {s.filter_words && <p className="mt-1 text-theme-xs text-gray-600 dark:text-gray-300">{s.filter_words}.</p>}
          {counted.length === 0 ? (
            <p className="mt-1 text-theme-xs text-gray-500 dark:text-gray-400">Nothing out of the ordinary was counted.</p>
          ) : (
            <ul className="mt-1 grid grid-cols-1 gap-x-6 text-theme-xs text-gray-600 sm:grid-cols-2 dark:text-gray-300">
              {counted.map(([k, v]) => <li key={k}><span className="tabular-nums">{v}</span> {COUNT_WORDS[k] ?? k}</li>)}
            </ul>
          )}
        </div>
      )}

      {opts && (
        <div className={card}>
          <h3 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">Tested ideas</h3>
          <p className="mt-1 max-w-3xl text-theme-xs text-gray-500 dark:text-gray-400">{opts.tested.words}</p>
          {opts.tested.store && <V3Check check={{ state: "ok", ...opts.tested.store }} kind="stored" />}
          <V3Check check={opts.tested.check} />
        </div>
      )}
    </div>
  );
}
