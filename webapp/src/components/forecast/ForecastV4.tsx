"use client";
/** AUTO TRADE -> FORECAST V4 — Forecast v2's two questions (which strategies are on a streak, and
 *  which switch-on rules make the most) asked of Backtest v4's trades: the Claude skills'
 *  strategies. Operator, Nov 10, 2026: "in auto trade can you create forecast v4 but this time use
 *  my backtest v4 data".
 *
 *  Every number is the server's (tradingagents/forecast_v4.py, /api/forecast-v4*): every filter is
 *  sent to it, it sorts and pages, ten a page under the Auto Trade buttons. This file only prints. */
import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { API_BASE, fmtMoney, fmtWhen } from "@/lib/api";
import PageButtons from "@/components/common/PageButtons";

type Month = { trades: number; wins: number; losses: number; profit: number; random: number; covered: boolean; complete: boolean };
type Top = { id: string; coin: string; tf: string; label: string; trades: number; profit: number };
type Rule = {
  id: string; window: number; min_win_rate: number; min_trades: number; words: string; money?: string;
  tf: string; skill: string; tp_rule: string; sl_cap: number; kind_n: number;
  widest_tp: number | null; widest_sl: number; pool_trades: number; pool_per_trade: number | null;
  trades: number; wins: number; losses: number; profit: number; win_rate: number | null;
  per_trade: number | null; break_even: number | null; worst_run: number; worst_run_n: number;
  worst_day: number | null; green_days: number; days_traded: number; days_covered: number;
  busiest_day: number; random_profit: number; random_per_trade: number | null; beat_days: number;
  luck: boolean; strategies: number; months: Month[];
  predicted: { profit: number; low: number; high: number; months: number; trades: number; thin: boolean } | null;
  rank: number | null; top: Top[];
};
type RulePage = { ready: boolean; why?: string; rows: Rule[]; total: number; of: number; page: number; pages: number; filters: string[] };
type Follow = { k: number; cases: number; capped: boolean; next_win: number | null; next10: number | null; enough: boolean };
type Streak = {
  id: string; coin: string; tf: string; label: string; skill: string; tp: number | null; sl: number;
  win: boolean; length: number; started_s: number; last_s: number; profit: number; trades: number;
  wins: number; win_rate: number | null; break_even: number | null; follow?: Follow;
};
type StreakPage = { ready: boolean; why?: string; rows: Streak[]; total: number; of: number; page: number; pages: number; filters: string[] };
type WalkMonth = { key: string; from_s: number; to_s: number; complete: boolean };
type Summary = {
  ready: boolean; why?: string; built_s: number; seconds: number;
  store: { built_s: number; data_end_s: number; strategies: number; trades: number; margin: number; leverage: number };
  used: { trades: number; left_out: number; left_out_why: string };
  walk: { from_s: number; to_s: number; days: number; months: WalkMonth[]; trades: number };
  coverage: Record<string, { strategies: number; trades: number; first_s: number | null }>;
  grid: { windows: number[]; win_rates: number[]; min_trades: number[]; tested: number; same_as_another: number; skills: string[];
    money?: string[]; money_words?: Record<string, string> };
  counts: { rules: number; traded: number; made_money: number; not_luck: number; win_streaks: number; loss_streaks: number };
  defaults: { win_n: number; loss_m: number; recent: number };
};

const MONTH = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const monthName = (key: string) => { const [y, m] = key.split("-"); return `${MONTH[Number(m) - 1] ?? m} ${y}`; };
const pct = (v: number | null | undefined) => (v == null ? "—" : `${v.toFixed(1)}%`);
const tone = (v: number | null | undefined) =>
  v == null ? "text-gray-500 dark:text-gray-400" : v > 0 ? "text-success-600" : v < 0 ? "text-error-500" : "text-gray-600 dark:text-gray-300";
const card = "min-w-0 rounded-2xl border border-gray-200 bg-white p-5 dark:border-white/[0.05] dark:bg-white/[0.03]";
const btn = "rounded-lg border border-gray-300 px-3 py-1 text-theme-xs text-gray-600 disabled:opacity-40 dark:border-gray-700 dark:text-gray-300";
const field = "rounded-lg border border-gray-300 bg-transparent px-2 py-1 text-theme-xs text-gray-700 dark:border-gray-700 dark:text-gray-200";
const th = "py-1.5 pr-3 text-start font-medium text-gray-500 dark:text-gray-400";
const td = "whitespace-nowrap py-1.5 pr-3 text-gray-700 dark:text-gray-300";
const num = (s: string) => s.replace(/[^0-9.]/g, "");

function getJson<T>(path: string, params: Record<string, string | number | boolean | undefined>): Promise<T> {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") p.set(k, String(v));
  return fetch(`${API_BASE}${path}?${p}`, { cache: "no-store" }).then((r) => {
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json() as Promise<T>;
  });
}

/** The newest answer only: a slow answer to an older question never paints over a newer one. */
function useServer<T>(path: string, params: Record<string, string | number | boolean | undefined>, delay = 350) {
  const [d, setD] = useState<T | null>(null);
  const [err, setErr] = useState("");
  const [done, setDone] = useState("");
  const ask = useRef(0);
  const key = JSON.stringify(params);
  useEffect(() => {
    const mine = ++ask.current;
    const t = setTimeout(() => {
      getJson<T>(path, JSON.parse(key))
        .then((r) => { if (mine === ask.current) { setD(r); setErr(""); } })
        .catch((e) => { if (mine === ask.current) setErr(String(e?.message ?? e)); })
        .finally(() => { if (mine === ask.current) setDone(path + key); });
    }, delay);
    return () => clearTimeout(t);
  }, [path, key, delay]);
  // busy until the answer to THIS question is in (derived, never set inside the effect)
  return { d, err, busy: done !== path + key };
}

function Badge({ kind, children }: { kind: "good" | "bad" | "info"; children: React.ReactNode }) {
  const c = kind === "good" ? "bg-success-50 text-success-700 dark:bg-success-500/15 dark:text-success-400"
    : kind === "bad" ? "bg-error-50 text-error-600 dark:bg-error-500/15"
    : "bg-gray-100 text-gray-600 dark:bg-white/[0.06] dark:text-gray-300";
  return <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${c}`}>{children}</span>;
}

// ---------------------------------------------------------------- streaks
function followText(f?: Follow) {
  if (!f) return "—";
  if (!f.enough) return `not enough past runs to tell (${f.cases.toLocaleString()} cases)`;
  return `next trade won ${pct(f.next_win)} of ${f.cases.toLocaleString()} times${f.next10 != null ? ` · next 10 made ${fmtMoney(f.next10)}` : ""}${f.capped ? ` (runs of ${f.k}+)` : ""}`;
}

function StreakList({ kind, initial, recentInit, base }: { kind: "win" | "loss"; initial: number; recentInit: number; base: number }) {
  const [min, setMin] = useState(String(initial));
  const [recent, setRecent] = useState(String(recentInit));
  const [tf, setTf] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const n = Math.max(1, Math.floor(Number(min) || initial));
  const { d, err, busy } = useServer<StreakPage>("/api/forecast-v4/streaks", {
    kind, min: n, recent: Math.max(0, Math.floor(Number(recent) || 0)), tf, q, base_margin: base, page,
  });
  const word = kind === "win" ? "wins" : "losses";
  const reset = () => setPage(1);
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">{kind === "win" ? "Winning" : "Losing"} streaks</p>
        <label className="flex items-center gap-1 text-theme-xs text-gray-500 dark:text-gray-400">at least
          <input aria-label={`${kind} streak at least`} className={`${field} w-14`} inputMode="numeric" value={min}
            onChange={(e) => { setMin(num(e.target.value)); reset(); }} /> {word} in a row</label>
        <label className="flex items-center gap-1 text-theme-xs text-gray-500 dark:text-gray-400">last trade in the data&apos;s last
          <input aria-label={`${kind} streak recent days`} className={`${field} w-12`} inputMode="numeric" value={recent}
            onChange={(e) => { setRecent(num(e.target.value)); reset(); }} /> days (0 = any)</label>
        <select aria-label={`${kind} streak timeframe`} className={field} value={tf} onChange={(e) => { setTf(e.target.value); reset(); }}>
          <option value="">every timeframe</option>
          {["15m", "30m", "1h", "4h", "1d"].map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <input aria-label={`${kind} streak coin or id`} placeholder="coin or #id" className={`${field} w-28`} value={q}
          onChange={(e) => { setQ(e.target.value); reset(); }} />
        {busy && <span className="text-[11px] text-gray-400">working…</span>}
      </div>
      {err && <p className="text-theme-xs text-error-500">could not read the streaks — {err}</p>}
      {d && !d.ready && <p className="text-theme-xs text-gray-500">{d.why}</p>}
      {d && d.ready && (
        <p className="text-[11px] text-gray-500 dark:text-gray-400">
          {d.total.toLocaleString()} of {d.of.toLocaleString()} {kind === "win" ? "winning" : "losing"} runs · {d.filters.join(" · ")}{d.why ? ` · ${d.why}` : ""}
        </p>
      )}
      {d && d.rows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-theme-xs">
            <thead><tr>
              {["ID", "coin", "TF", "strategy", "TP / SL", "in a row", "started → last trade", "profit in it", "its record", "needs to break even", "after a run this long"].map((h) => <th key={h} className={th}>{h}</th>)}
            </tr></thead>
            <tbody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
              {d.rows.map((s) => (
                <tr key={s.id}>
                  <td className={`${td} font-mono`}>#{s.id}</td>
                  <td className={`${td} font-semibold`}>{s.coin}</td>
                  <td className={td}>{s.tf}</td>
                  <td className={td}>{s.label}<span className="text-gray-400"> · {s.skill}</span></td>
                  <td className={td}>{s.tp != null ? `${s.tp}%` : "no target"} / {s.sl}%</td>
                  <td className={`${td} font-semibold ${kind === "win" ? "text-success-600" : "text-error-500"}`}>{s.length}</td>
                  <td className={td}>{fmtWhen(s.started_s)} → {fmtWhen(s.last_s)}</td>
                  <td className={`${td} ${tone(s.profit)}`}>{fmtMoney(s.profit)}</td>
                  <td className={td}>{s.trades.toLocaleString()} trades · {s.wins.toLocaleString()} won · {pct(s.win_rate)}</td>
                  <td className={td}>{pct(s.break_even)}</td>
                  <td className={td}>{followText(s.follow)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {d && <PageButtons cur={d.page} pages={d.pages} goto={setPage} what={`${kind} streak`} busy={busy} />}
    </div>
  );
}

// ---------------------------------------------------------------- rule sets
/** The money rules the grid crossed with every win rate (Nov 11, 2026), in the server's own words. */
function moneyRules(s: Summary) {
  const m = (s.grid.money ?? []).flatMap((x) => (x ? [s.grid.money_words?.[x]?.replace(" over them", "") ?? x] : []));
  return m.length ? `no money rule / ${m.join(" / ")}` : "no money rule";
}

function tpText(r: Rule) {
  if (r.tp_rule === ">") return `wider than SL, up to ${r.widest_tp}%`;
  return r.widest_tp == null ? "any (some have none)" : `any, up to ${r.widest_tp}%`;
}

function RuleRow({ r, open, toggle, s }: { r: Rule; open: boolean; toggle: () => void; s: Summary }) {
  const p = r.predicted;
  const days = Math.max(1, r.days_covered);
  return (
    <Fragment>
      <tr className="align-top">
        <td className={`${td} font-semibold`}>
          <button type="button" className="font-mono text-brand-500 hover:underline" onClick={toggle} aria-expanded={open}>#{r.id}</button>
        </td>
        <td className="min-w-[280px] max-w-[420px] py-1.5 pr-3 text-theme-xs text-gray-700 dark:text-gray-300">{r.words}</td>
        <td className={`${td} font-semibold ${tone(p?.profit)}`}>{p ? <>{fmtMoney(p.profit)} <span className="font-normal text-gray-400">({fmtMoney(p.low)} to {fmtMoney(p.high)})</span>{p.thin && <span className="ml-1"><Badge kind="info">thin</Badge></span>}</> : "no whole month"}</td>
        <td className={`${td} font-semibold ${tone(r.profit)}`}>{fmtMoney(r.profit)}</td>
        <td className={td}>{tpText(r)}</td>
        <td className={td}>up to {r.widest_sl}%</td>
        <td className={td}>{s.store.leverage}x</td>
        <td className={td}>{r.trades.toLocaleString()} <span className="text-gray-400">({(r.trades / days).toFixed(1)} a day)</span></td>
        <td className={td}>{r.wins.toLocaleString()} / {r.losses.toLocaleString()} <span className="text-gray-400">({(r.wins / days).toFixed(1)} / {(r.losses / days).toFixed(1)} a day)</span></td>
        <td className={td}>{pct(r.win_rate)} <span className="text-gray-400">needs {pct(r.break_even)}</span></td>
        <td className={`${td} text-error-500`}>{fmtMoney(r.worst_run)} over {r.worst_run_n}</td>
        <td className={`${td} ${tone(r.worst_day)}`}>{fmtMoney(r.worst_day)}</td>
        <td className={td}>{r.days_traded ? `${r.beat_days} of ${r.days_traded} days` : "—"}{r.trades > 0 && r.luck && <span className="ml-1"><Badge kind="bad">could be luck</Badge></span>}</td>
      </tr>
      {open && (
        <tr>
          <td colSpan={13} className="pb-3">
            {/* sticky + a width of its own: the table is 1,400px wide inside a scrolling card, and the
                detail would otherwise run off the card's right edge (seen Nov 10, 2026) */}
            <div className="sticky left-0 w-[60rem] max-w-[calc(100vw-4rem)] whitespace-normal rounded-xl bg-gray-50 p-3 text-theme-xs text-gray-600 lg:max-w-[calc(100vw-24rem)] dark:bg-white/[0.03] dark:text-gray-300">
              <p>
                <b>{r.words}</b>: about <b className={tone(p?.profit)}>{p ? fmtMoney(p.profit) : "—"}</b> a month
                {p ? ` (the average of ${p.months} whole month${p.months === 1 ? "" : "s"}, about ${p.trades.toLocaleString()} trades each)` : ""} ·
                TOTAL PROFIT {fmtMoney(r.profit)} over {r.trades.toLocaleString()} trades from {fmtWhen(s.walk.from_s)} to {fmtWhen(s.walk.to_s)}
                ({fmtMoney(r.per_trade)} a trade; random picks of the same kind {fmtMoney(r.random_per_trade)} a trade, {fmtMoney(r.random_profit)} in all) ·
                beat random on {r.beat_days} of {r.days_traded} days it traded{r.luck ? " — could be luck" : ""} ·
                {" "}{r.strategies.toLocaleString()} of its kind&apos;s {r.kind_n.toLocaleString()} strategies traded · green on {r.green_days} days · busiest day {r.busiest_day.toLocaleString()} trades opened.
              </p>
              <div className="mt-2 overflow-x-auto">
                <table className="text-theme-xs">
                  <thead><tr>{["month", "trades", "won / lost", "profit", "random picks, same trades"].map((h) => <th key={h} className={th}>{h}</th>)}</tr></thead>
                  <tbody>{r.months.map((m, i) => (
                    <tr key={s.walk.months[i]?.key ?? i}>
                      <td className={td}>{monthName(s.walk.months[i]?.key ?? "")}{!m.complete && <span className="text-gray-400"> (so far, to {fmtWhen(s.walk.to_s)})</span>}{!m.covered && <span className="text-gray-400"> · no data of this kind</span>}</td>
                      <td className={td}>{m.trades.toLocaleString()}</td>
                      <td className={td}>{m.wins.toLocaleString()} / {m.losses.toLocaleString()}</td>
                      <td className={`${td} ${tone(m.profit)}`}>{fmtMoney(m.profit)}</td>
                      <td className={`${td} ${tone(m.random)}`}>{fmtMoney(m.random)}</td>
                    </tr>))}
                    <tr className="border-t border-gray-200 dark:border-gray-700">
                      <td className={`${td} font-semibold`}>TOTAL PROFIT</td>
                      <td className={td}>{r.trades.toLocaleString()}</td>
                      <td className={td}>{r.wins.toLocaleString()} / {r.losses.toLocaleString()}</td>
                      <td className={`${td} font-semibold ${tone(r.profit)}`}>{fmtMoney(r.profit)}</td>
                      <td className={`${td} ${tone(r.random_profit)}`}>{fmtMoney(r.random_profit)}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              {r.top.length > 0 && (
                <p className="mt-2">The strategies it switched on most (look them up by id in Backtest v4):{" "}
                  {r.top.map((t, i) => <span key={t.id}>{i ? " · " : ""}<span className="font-mono">#{t.id}</span> {t.coin} {t.tf} {t.label}: {t.trades.toLocaleString()} trades, <span className={tone(t.profit)}>{fmtMoney(t.profit)}</span></span>)}
                </p>
              )}
            </div>
          </td>
        </tr>
      )}
    </Fragment>
  );
}

type RQ = {
  window: string; tf: string; skill: string; tp_rule: string; money: string; max_tp: string; max_sl: string;
  min_winrate: string; min_trades: string; min_profit: string; profitable: boolean; not_luck: boolean;
  untraded: boolean; q: string; sort: string; desc: boolean;
};
const RQ0: RQ = { window: "", tf: "", skill: "", tp_rule: "", money: "", max_tp: "", max_sl: "", min_winrate: "", min_trades: "",
  min_profit: "", profitable: false, not_luck: false, untraded: false, q: "", sort: "rank", desc: true };

function Rules({ s, base }: { s: Summary; base: number }) {
  const [f, setF] = useState<RQ>(RQ0);
  const [page, setPage] = useState(1);
  // null = not chosen (a found id opens by itself), "" = closed by hand, else the open row's id
  const [open, setOpen] = useState<string | null>(null);
  const set = (k: Partial<RQ>) => { setF((x) => ({ ...x, ...k })); setPage(1); setOpen(null); };
  const { d, err, busy } = useServer<RulePage>("/api/forecast-v4/rules", {
    window: f.window, tf: f.tf, skill: f.skill, tp_rule: f.tp_rule, money: f.money, max_tp: f.max_tp, max_sl: f.max_sl,
    min_winrate: f.min_winrate, min_trades: f.min_trades, min_profit: f.min_profit,
    profitable: f.profitable || undefined, not_luck: f.not_luck || undefined, traded: !f.untraded,
    q: f.q, sort: f.sort, desc: f.desc, base_margin: base, page,
  });
  // FIND BY ID opens that row's detail (CLAUDE.md kit H)
  const want = f.q.trim().replace(/^#/, "").toUpperCase();
  const first = d?.rows[0]?.id;
  const isOpen = (id: string) => open === id || (open === null && want !== "" && id === first);
  const w = s.walk;
  return (
    <div className={card}>
      <h3 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">Best switch-on rules this month</h3>
      <p className="mt-1 text-[11px] text-gray-500 dark:text-gray-400">
        ${base.toLocaleString()} margin a trade at {s.store.leverage}x leverage (${(base * s.store.leverage).toLocaleString()} of coin; the stored trades were measured at ${s.store.margin} and every dollar here is scaled) ·
        {" "}<b>{s.grid.tested.toLocaleString()} rule sets tested</b> ({s.grid.windows.join(" / ")} days judged × {s.grid.win_rates.map((x) => (x ? `${x}%` : "any")).join(" / ")} wins × {s.grid.min_trades.join(" / ")}+ trades × {moneyRules(s)} × TP rule × stop ceiling × timeframe × skill; {s.grid.same_as_another.toLocaleString()} more switched on exactly the same strategies as one listed, so they are listed once) ·
        walked day by day from the start of {monthName(w.months[0]?.key ?? "")} (12:00am UTC, {fmtWhen(w.from_s)} on this PC&apos;s clock) to {fmtWhen(w.to_s)} ({w.days} days, {w.trades.toLocaleString()} trades opened): every day at 12:00am UTC each rule set switches on the strategies whose trades that closed in the days before pass it, and counts the trades they open that day ·
        &quot;this month&quot; is the average of the whole months {w.months.flatMap((m) => (m.complete ? [monthName(m.key)] : [])).join(", ")}, low to high in brackets ·
        random picks = the same trades at the average trade every strategy of the same kind opened that day ·
        every switched-on strategy&apos;s trades count, even several on one coin at the same time (a room holds one position per coin) ·
        &quot;best worst month first&quot; lists the rule sets judged on every whole month before the thin ones
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-theme-xs">
        <input aria-label="find a rule set by id" placeholder="find #id" className={`${field} w-24`} value={f.q} onChange={(e) => set({ q: e.target.value })} />
        <select aria-label="days judged" className={field} value={f.window} onChange={(e) => set({ window: e.target.value })}>
          <option value="">any days judged</option>
          {s.grid.windows.map((x) => <option key={x} value={x}>judged on {x} days</option>)}
        </select>
        <select aria-label="timeframe" className={field} value={f.tf} onChange={(e) => set({ tf: e.target.value })}>
          <option value="">every timeframe rule</option>
          <option value="any">any-timeframe rules only</option>
          {["15m", "30m", "1h", "4h", "1d"].map((t) => <option key={t} value={t}>{t} only</option>)}
        </select>
        <select aria-label="skill" className={field} value={f.skill} onChange={(e) => set({ skill: e.target.value })}>
          <option value="">every skill rule</option>
          <option value="any">any-skill rules only</option>
          {s.grid.skills.flatMap((k) => (k ? [<option key={k} value={k}>{k}</option>] : []))}
        </select>
        <select aria-label="money rule" className={field} value={f.money} onChange={(e) => set({ money: e.target.value })}>
          <option value="">win rate and money rules</option>
          <option value="none">win rate alone</option>
          {(s.grid.money ?? []).flatMap((m) => (m ? [<option key={m} value={m}>{s.grid.money_words?.[m]?.replace(" over them", "") ?? m}</option>] : []))}
        </select>
        <select aria-label="TP rule" className={field} value={f.tp_rule} onChange={(e) => set({ tp_rule: e.target.value })}>
          <option value="">any TP rule</option>
          <option value=">">TP wider than SL</option>
          <option value="any">any TP</option>
        </select>
        <label className="flex items-center gap-1 text-gray-500 dark:text-gray-400">max TP %<input aria-label="max TP %" className={`${field} w-12`} inputMode="decimal" value={f.max_tp} onChange={(e) => set({ max_tp: num(e.target.value) })} /></label>
        <label className="flex items-center gap-1 text-gray-500 dark:text-gray-400">max SL %<input aria-label="max SL %" className={`${field} w-12`} inputMode="decimal" value={f.max_sl} onChange={(e) => set({ max_sl: num(e.target.value) })} /></label>
        <label className="flex items-center gap-1 text-gray-500 dark:text-gray-400">min win rate %<input aria-label="min win rate %" className={`${field} w-12`} inputMode="decimal" value={f.min_winrate} onChange={(e) => set({ min_winrate: num(e.target.value) })} /></label>
        <label className="flex items-center gap-1 text-gray-500 dark:text-gray-400">min trades<input aria-label="min trades" className={`${field} w-14`} inputMode="numeric" value={f.min_trades} onChange={(e) => set({ min_trades: num(e.target.value) })} /></label>
        <label className="flex items-center gap-1 text-gray-500 dark:text-gray-400">min profit $<input aria-label="min profit $" className={`${field} w-16`} inputMode="decimal" value={f.min_profit} onChange={(e) => set({ min_profit: e.target.value.replace(/[^0-9.-]/g, "") })} /></label>
        <label className="flex items-center gap-1 text-gray-500 dark:text-gray-400"><input type="checkbox" checked={f.profitable} onChange={(e) => set({ profitable: e.target.checked })} /> made money</label>
        <label className="flex items-center gap-1 text-gray-500 dark:text-gray-400"><input type="checkbox" checked={f.not_luck} onChange={(e) => set({ not_luck: e.target.checked })} /> beat random by more than luck</label>
        <label className="flex items-center gap-1 text-gray-500 dark:text-gray-400"><input type="checkbox" checked={f.untraded} onChange={(e) => set({ untraded: e.target.checked })} /> show rule sets that never traded</label>
        <select aria-label="sort the rule sets" className={field} value={f.sort} onChange={(e) => set({ sort: e.target.value })}>
          <option value="rank">best worst month first</option>
          <option value="predicted">this month, predicted</option>
          <option value="profit">PROFIT / TOTAL $</option>
          <option value="per_trade">profit a trade</option>
          <option value="beat">beat random (share of days)</option>
          <option value="winrate">win rate</option>
          <option value="trades">trades</option>
          <option value="worst_run">worst losing run</option>
        </select>
        <button type="button" className={btn} onClick={() => set({ desc: !f.desc })}>{f.desc ? "highest first" : "lowest first"}</button>
        <button type="button" className={btn} onClick={() => { setF(RQ0); setPage(1); setOpen(null); }}>clear all</button>
        {busy && <span className="text-[11px] text-gray-400">working…</span>}
      </div>
      {err && <p className="mt-2 text-theme-xs text-error-500">could not read the rule sets — {err}</p>}
      {d && d.ready && (
        <p className="mt-2 text-[11px] text-gray-500 dark:text-gray-400">
          {d.total.toLocaleString()} rule set{d.total === 1 ? "" : "s"} of {d.of.toLocaleString()} tested{d.filters.length ? ` · ${d.filters.join(" · ")}` : ""}{d.why ? ` · ${d.why}` : ""}
        </p>
      )}
      {d && d.rows.length > 0 && (
        <div className="mt-2 max-w-full overflow-x-auto">
          <table className="w-full min-w-[1400px] text-theme-xs">
            <thead><tr>
              {["ID", "rule set", "this month — predicted (low to high)", "PROFIT / TOTAL $", "TP", "SL", "leverage", "trades", "wins / losses", "win rate", "worst losing run", "worst day", "beat random"].map((h) => <th key={h} className={th}>{h}</th>)}
            </tr></thead>
            <tbody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
              {d.rows.map((x) => <RuleRow key={x.id} r={x} s={s} open={isOpen(x.id)} toggle={() => setOpen(isOpen(x.id) ? "" : x.id)} />)}
            </tbody>
          </table>
        </div>
      )}
      {d && <PageButtons cur={d.page} pages={d.pages} goto={setPage} what="rule set" busy={busy} />}
    </div>
  );
}

export default function ForecastV4() {
  const [s, setS] = useState<Summary | null>(null);
  const [err, setErr] = useState("");
  const [baseText, setBaseText] = useState("5");
  const base = Number(baseText) > 0 ? Number(baseText) : 5;
  const load = useCallback(() => {
    fetch(`${API_BASE}/api/forecast-v4`, { cache: "no-store" })
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then((r: Summary) => { setS(r); setErr(""); })
      .catch((e) => setErr(String(e?.message ?? e)));
  }, []);
  useEffect(() => { load(); }, [load]);
  return (
    <div className="flex flex-col gap-5">
      <div className={card}>
        <h2 className="text-theme-xl font-semibold text-gray-800 dark:text-white/90">Forecast v4 — from Backtest v4</h2>
        {err && <p className="mt-1 text-theme-xs text-error-500">could not read Forecast v4 — {err}</p>}
        {s && !s.ready && <p className="mt-1 text-theme-xs text-gray-500">{s.why}</p>}
        {s && s.ready && (
          <p className="mt-1 text-[11px] text-gray-500 dark:text-gray-400">
            From Backtest v4: {s.store.strategies.toLocaleString()} Claude-skill strategies and {s.store.trades.toLocaleString()} trades, last candle {fmtWhen(s.store.data_end_s)}, filed {fmtWhen(s.store.built_s)} ·
            worked out {fmtWhen(s.built_s)} · {s.used.left_out.toLocaleString()} trades left out: {s.used.left_out_why} ·
            each timeframe starts where its candles do ({Object.entries(s.coverage).map(([tf, c]) => `${tf} from ${c.first_s ? fmtWhen(c.first_s) : "never"}`).join(", ")}) ·
            Backtest v4 is not updated by itself, so this is as of its last candle ·
            {" "}<b>nothing here switches anything on</b>: no room can run a skill strategy, and no practice account has traded one, so there is no reality check
          </p>
        )}
        <label className="mt-2 flex items-center gap-2 text-theme-xs text-gray-500 dark:text-gray-400">base margin $
          <input aria-label="base margin $" className={`${field} w-16`} inputMode="decimal" value={baseText} onChange={(e) => setBaseText(num(e.target.value))} />
          <span>every dollar on this page is scaled to it</span>
        </label>
      </div>
      {s && s.ready && (
        <>
          <div className={card}>
            <h3 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">Streaks</h3>
            <p className="mt-1 text-[11px] text-gray-500 dark:text-gray-400">wins (or losses) in a row ending with each strategy&apos;s newest trade · {s.counts.win_streaks.toLocaleString()} winning and {s.counts.loss_streaks.toLocaleString()} losing runs of 3 or more · &quot;after a run this long&quot; is what every past run of the same length did next, over every strategy&apos;s whole history</p>
            <div className="mt-3 grid min-w-0 gap-6 2xl:grid-cols-2 [&>*]:min-w-0">
              <StreakList kind="win" initial={s.defaults.win_n} recentInit={s.defaults.recent} base={base} />
              <StreakList kind="loss" initial={s.defaults.loss_m} recentInit={s.defaults.recent} base={base} />
            </div>
          </div>
          <Rules s={s} base={base} />
        </>
      )}
    </div>
  );
}
