"use client";
/** AUTO TRADE -> FORECAST V2 — which coins are on a streak, and which room
 *  rules will make the most this month. ("Where the money goes", the what-if
 *  box and "This month so far" went on Oct 08, 2026: "i dont need it
 *  anymore".)
 *
 *  Operator, Oct 01, 2026: "you are seeing a coin is winning 9 streak then
 *  inform me that specific coin i want it in a Streak section / then predict
 *  what combination of room will be effective, for example: 90% winrate with
 *  40trade, tp is greater than SL will have profit of x this month", then
 *  "okay run that prompt and create Forecast v2" (docs/FORECAST-V2.md).
 *
 *  Every number is worked out on the server (tradingagents/forecast_v2*.py);
 *  every list is filtered, sorted and paged there, ten a page under the Auto
 *  Trade buttons (Oct 02, 2026: "in forecast, make it paginated just like in
 *  auto trade"). This file only prints. */
import { Fragment, type ReactNode, useCallback, useState } from "react";
import {
  api, fmtMoney, fmtWhen, fmtWhenMs, F2Rule, F2RulePage, F2RuleQuery, F2Streak, F2StreakPage,
  F2Summary,
} from "@/lib/api";
import { useLiveRefresh } from "@/lib/live";
import PageButtons from "@/components/common/PageButtons";

const roomName = (id: string) => (id === "main" ? "Main" : `#${id}`);
const pct = (v: number | null | undefined) => (v == null ? "—" : `${v.toFixed(1)}%`);
const tone = (v: number | null | undefined) =>
  v == null ? "text-gray-500 dark:text-gray-400" : v >= 0 ? "text-success-600" : "text-error-500";
// min-w-0: a card is a flex child, and a wide table inside would otherwise
// widen the card and the whole page (measured: 1,590px at a 1,440px window)
const card = "min-w-0 rounded-2xl border border-gray-200 bg-white p-5 dark:border-white/[0.05] dark:bg-white/[0.03]";
const btn = "rounded-lg border border-gray-300 px-3 py-1 text-theme-xs text-gray-600 disabled:opacity-40 dark:border-gray-700 dark:text-gray-300";
const field = "rounded-lg border border-gray-300 bg-transparent px-2 py-1 text-theme-xs text-gray-700 dark:border-gray-700 dark:text-gray-200";
const th = "py-1.5 pr-3 text-start font-medium text-gray-500 dark:text-gray-400";
const td = "whitespace-nowrap py-1.5 pr-3 text-gray-700 dark:text-gray-300";
const MONTH = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const monthName = (key: string) => {
  const [y, m] = key.split("-");
  return `${MONTH[Number(m) - 1] ?? m} ${y}`;
};

function Badge({ kind, children }: { kind: "good" | "bad" | "info"; children: React.ReactNode }) {
  const c = kind === "good" ? "bg-success-50 text-success-700 dark:bg-success-500/15 dark:text-success-400"
    : kind === "bad" ? "bg-error-50 text-error-600 dark:bg-error-500/15"
    : "bg-gray-100 text-gray-600 dark:bg-white/[0.06] dark:text-gray-300";
  return <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${c}`}>{children}</span>;
}

// ---------------------------------------------------------------- A. streaks
function followText(s: F2Streak) {
  const f = s.follow;
  if (!f) return "—";
  if (!f.enough) return `not enough past streaks to tell (${f.cases.toLocaleString()} cases)`;
  return `next trade won ${f.next_win}% of ${f.cases.toLocaleString()} times${f.next10 != null ? ` · next 10 made ${fmtMoney(f.next10)}` : ""}${f.capped ? ` (runs of ${f.k}+)` : ""}`;
}

function StreakList({ kind, initial }: { kind: "win" | "loss"; initial: number }) {
  const [source, setSource] = useState<"practice" | "backtest">("practice");
  const [min, setMin] = useState(String(initial));
  const [page, setPage] = useState(1);
  const [d, setD] = useState<F2StreakPage | null>(null);
  const [err, setErr] = useState("");
  const n = Math.max(1, Math.floor(Number(min) || initial));
  const load = useCallback(() => {
    api.forecastV2Streaks({ source, kind, min: n, page })
      .then((r) => { setD(r); setErr(""); })
      .catch((e) => setErr(String(e?.message ?? e)));
  }, [source, kind, n, page]);
  useLiveRefresh(load, 30_000, [load]);
  const word = kind === "win" ? "wins" : "losses";
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">{kind === "win" ? "Winning" : "Losing"} streaks</p>
        <select aria-label={`${kind} streak source`} className={field} value={source}
          onChange={(e) => { setSource(e.target.value as "practice" | "backtest"); setPage(1); }}>
          <option value="practice">practice account</option>
          <option value="backtest">backtest</option>
        </select>
        <label className="flex items-center gap-1 text-theme-xs text-gray-500 dark:text-gray-400">
          at least
          <input aria-label={`${kind} streak at least`} className={`${field} w-14`} inputMode="numeric" value={min}
            onChange={(e) => { setMin(e.target.value.replace(/[^0-9]/g, "")); setPage(1); }} />
          {word} in a row
        </label>
      </div>
      {err && <p className="text-theme-xs text-error-500">could not read the streaks — {err}</p>}
      {d && (
        <p className="text-[11px] text-gray-500 dark:text-gray-400">
          {d.total.toLocaleString()} of {d.of.toLocaleString()} {d.source === "practice" ? "room and coin" : "strategy"} {kind === "win" ? "winning" : "losing"} runs are {d.min}+ {word} in a row · examined: {d.examined.what}
          {d.source === "practice" ? ` (${(d.examined.rows ?? 0).toLocaleString()} runs in ${d.examined.rooms} rooms)` : d.examined.strategies != null ? ` (${d.examined.strategies.toLocaleString()} strategies, ${(d.examined.trades ?? 0).toLocaleString()} trades, to ${fmtWhenMs(d.examined.end_ms ?? 0)})` : " — no replay measured yet"}
          {d.note ? ` · ${d.note}` : ""}
        </p>
      )}
      {d && d.rows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-theme-xs">
            <thead><tr>
              {["coin", d.source === "practice" ? "room" : "strategy", "TP / SL", "in a row", "started → last trade", "profit in it", "its record", "needs to break even", "switched on in", "after a run this long"].map((h) => <th key={h} className={th}>{h}</th>)}
            </tr></thead>
            <tbody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
              {d.rows.map((s, i) => (
                <tr key={`${s.room ?? ""}-${s.id ?? ""}-${s.coin}-${i}`}>
                  <td className={`${td} font-semibold`}>{s.coin}</td>
                  <td className={td}>{s.source === "practice"
                    ? <>{s.room_name}{s.strategies && s.strategies > 1 ? <span className="text-gray-400"> · {s.strategies} strategies</span> : s.signal ? <span className="text-gray-400"> · {s.tf} {s.signal}</span> : null}</>
                    : <>#{s.id}<span className="text-gray-400"> · {s.tf} {s.signal}</span></>}</td>
                  <td className={td}>{s.tp != null && s.sl != null ? `${s.tp}% / ${s.sl}%` : "mixed"}</td>
                  <td className={`${td} font-semibold ${kind === "win" ? "text-success-600" : "text-error-500"}`}>{s.length}</td>
                  <td className={td}>{fmtWhenMs(s.started_ms ?? (s.started_at ?? 0) * 1000)} → {fmtWhenMs(s.last_ms ?? (s.last_at ?? 0) * 1000)}</td>
                  <td className={`${td} ${tone(s.profit)}`}>{fmtMoney(s.profit)}</td>
                  <td className={td}>{s.trades.toLocaleString()} trades · {s.wins.toLocaleString()} won{s.source === "backtest" ? " (last 30 days)" : ` · ${pct(s.winrate)}`}</td>
                  <td className={td}>{pct(s.break_even)}</td>
                  <td className={td}>{s.source === "practice" ? (s.switched_on ? s.room_name : "switched off") : (s.rooms_on && s.rooms_on.length ? s.rooms_on.map(roomName).join(", ") : "none")}</td>
                  <td className={td}>{followText(s)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {d && <PageButtons cur={d.page} pages={d.pages} goto={setPage} what={`${kind} streak`} />}
    </div>
  );
}

// B. coins to avoid: removed Oct 07, 2026 (operator: "remove the section
// coins to avoid i dont need its logic") — the list, its route and its
// what-if option went with it
// --------------------------------------------------- C. where the money goes
// ------------------------------------------------------- D. best room rules
function range(p: { profit: number; low: number; high: number } | null | undefined) {
  if (!p) return "—";
  return `${fmtMoney(p.profit)} (${fmtMoney(p.low)} to ${fmtMoney(p.high)})`;
}

function corrRange(p: F2Rule["predicted"]) {
  if (!p || p.corrected == null) return "not measured";
  return `${fmtMoney(p.corrected)} (${fmtMoney(p.corrected_low)} to ${fmtMoney(p.corrected_high)})`;
}

function RuleRow({ r, open, toggle }: { r: F2Rule; open: boolean; toggle: () => void }) {
  const p = r.predicted;
  return (
    <Fragment>
      <tr className="align-top">
        <td className={`${td} font-semibold`}>
          <button type="button" className="text-brand-500 hover:underline" onClick={toggle} aria-expanded={open}>#{r.id}</button>
          {r.room && <span className="ml-1"><Badge kind="info">{roomName(r.room)}&apos;s rules</Badge></span>}
        </td>
        <td className="min-w-[300px] max-w-[460px] py-1.5 pr-3 text-theme-xs text-gray-700 dark:text-gray-300">{r.words}</td>
        <td className={`${td} ${tone(p?.profit)}`}>{range(p)}</td>
        <td className={`${td} font-semibold ${tone(p?.corrected)}`}>{corrRange(p)}</td>
        <td className={td}>{p ? p.trades.toLocaleString() : "—"}</td>
        <td className={td}>{r.total.wins.toLocaleString()} / {r.total.losses.toLocaleString()}</td>
        <td className={td}>{pct(r.total.winrate)} <span className="text-gray-400">needs {pct(r.break_even)}</span></td>
        <td className={`${td} text-error-500`}>{fmtMoney(r.total.worst_run)} over {r.total.worst_run_n}</td>
        <td className={td}>{r.total.max_open.toLocaleString()} → ${r.money_needed.toLocaleString()}</td>
        <td className={td}>{r.random.beat == null ? "—" : `${r.random.beat} in ${r.random.draws}`}{r.luck && <span className="ml-1"><Badge kind="bad">could be luck</Badge></span>}</td>
        <td className={td}>{r.deployable ? <Badge kind="good">yes</Badge> : <Badge kind="info">needs a new switch</Badge>}</td>
      </tr>
      {open && (
        <tr>
          <td colSpan={11} className="pb-3">
            <div className="rounded-xl bg-gray-50 p-3 text-theme-xs text-gray-600 dark:bg-white/[0.03] dark:text-gray-300">
              <p>
                <b>{r.words}</b>: about <b className={tone(p?.corrected)}>{p?.corrected != null ? fmtMoney(p.corrected) : "—"}</b> this month after the reality check
                (backtest says {p ? fmtMoney(p.profit) : "—"}; past months {r.months.filter((m) => m.complete).map((m) => fmtMoney(m.profit)).join(", ")}),
                about {p ? p.trades.toLocaleString() : "—"} trades, needs ${r.money_needed.toLocaleString()} in the wallet,
                {r.random.beat != null ? ` beat random ${r.random.beat} times in ${r.random.draws} (profit a trade ${fmtMoney(r.per_trade)} against random's ${fmtMoney(r.random.per_trade)})` : " not compared with random"}.
                {p?.thin ? " Built on fewer than 3 past months — thin." : ""}
              </p>
              {!r.deployable && <p className="mt-1 text-gray-500">{r.deploy_why}</p>}
              <div className="mt-2 overflow-x-auto">
                <table className="text-theme-xs">
                  <thead><tr>{["month", "trades", "won / lost", "profit", "after the reality check"].map((h) => <th key={h} className={th}>{h}</th>)}</tr></thead>
                  <tbody>{r.months.map((m) => (
                    <tr key={m.month}>
                      <td className={td}>{monthName(m.month)}{!m.complete && <span className="text-gray-400"> (so far)</span>}</td>
                      <td className={td}>{m.trades.toLocaleString()}</td>
                      <td className={td}>{m.wins.toLocaleString()} / {m.losses.toLocaleString()}</td>
                      <td className={`${td} ${tone(m.profit)}`}>{fmtMoney(m.profit)}</td>
                      <td className={`${td} ${tone(m.corrected)}`}>{fmtMoney(m.corrected)}</td>
                    </tr>))}
                  </tbody>
                </table>
              </div>
              <p className="mt-1 text-[10px] text-gray-400">{r.slots.toLocaleString()} strategies switched on over the replay · worst day {fmtMoney(r.total.worst_day)} · {r.total.green_days} green days of {r.total.days_n}</p>
            </div>
          </td>
        </tr>
      )}
    </Fragment>
  );
}

function Rules({ s }: { s: F2Summary }) {
  const [q, setQ] = useState<F2RuleQuery>({ sort: "rank", page: 1 });
  const [d, setD] = useState<F2RulePage | null>(null);
  const [err, setErr] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const load = useCallback(() => {
    api.forecastV2Rules(q).then((r) => { setD(r); setErr(""); }).catch((e) => setErr(String(e?.message ?? e)));
  }, [q]);
  useLiveRefresh(load, 60_000, [load]);
  const set = (k: Partial<F2RuleQuery>) => setQ((x) => ({ ...x, ...k, page: k.page ?? 1 }));
  const bt = s.backtest;
  // THE NUMBERS THE PREDICTIONS WERE CORRECTED WITH (bug hunt, round 2): the
  // live box drifted from the table it explains as practice trades closed
  const r = bt?.reality ?? s.reality.all;
  const now = s.reality.all;
  return (
    <div className={card}>
      <h3 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">Best room rules this month</h3>
      {bt ? (
        <p className="mt-1 text-[11px] text-gray-500 dark:text-gray-400">
          $5 margin a trade at 20x leverage ($100 of coin) · {bt.tested.total.toLocaleString()} rule sets tested ({bt.tested.base.toLocaleString()} base + {bt.tested.options.toLocaleString()} with one option) ·
          backtest months {bt.data.complete.map(monthName).join(", ")} (to {fmtWhenMs(bt.data.end_ms)}) · each rule set walked forward day by day, switching strategies on with data from before that day only, all three costs charged ·
          replay of {bt.data.strategies.toLocaleString()} strategies that could pass {bt.data.write ? `${bt.data.write.wr}% / ${bt.data.write.trades} trades / TP ${bt.data.write.tp}` : ""}
          {bt.data.write && bt.data.write.tp === ">" ? " — so \"any TP\" here is the same as TP wider than SL" : ""} · made {fmtWhen(bt.made_at)}
          {bt.data.of && bt.data.machines < bt.data.of ? <b> · PART OF THE MARKET: the coins of {bt.data.machines} of the run&apos;s {bt.data.of} machines — the others failed on GitHub</b> : null}
        </p>
      ) : <p className="mt-1 text-theme-xs text-gray-400">no rule set has been measured yet — the daily Forecast v2 run on GitHub makes the first one ({s.chain.why || "waiting"})</p>}
      <div className="mt-3 rounded-xl border border-gray-200 p-3 text-theme-xs text-gray-600 dark:border-gray-700 dark:text-gray-300">
        <b>Reality check</b> — the same rows over the same hours, from each switch-on to the end of its rebuilt backtest:
        {r.bt_trades ? <> practice took <b>{r.pr_trades.toLocaleString()}</b> of the backtest&apos;s {r.bt_trades.toLocaleString()} trades ({pct((r.took ?? 0) * 100)}) and made <b>{fmtMoney(r.gap == null ? null : -r.gap)}</b> a trade against the backtest
          (backtest {fmtMoney(r.bt_per_trade)} a trade, {pct(r.bt_winrate)} won; practice {fmtMoney(r.pr_per_trade)} a trade, {pct(r.pr_winrate)} won), from {r.rows.toLocaleString()} switched-on rows.
          So every prediction is shown twice: as the backtest says, and corrected — taken trades × (backtest profit a trade − {fmtMoney(r.gap)}).
          {bt && now.bt_trades && (now.took !== r.took || now.gap !== r.gap) ? <span className="text-gray-400"> Measured when the predictions were made ({fmtWhen(bt.made_at)}); right now it reads {pct((now.took ?? 0) * 100)} taken and {fmtMoney(now.gap == null ? null : -now.gap)} a trade.</span> : null}</>
          : <> nothing to compare yet — no room has practice trades inside its rebuilt backtest.</>}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-theme-xs">
        <select aria-label="sort the rule sets" className={field} value={q.sort} onChange={(e) => set({ sort: e.target.value })}>
          <option value="rank">best worst month first</option>
          <option value="corrected">corrected prediction</option>
          <option value="predicted">backtest prediction</option>
          <option value="beat">beat random</option>
          <option value="winrate">win rate</option>
          <option value="trades">trades</option>
          <option value="money">money needed</option>
        </select>
        <select aria-label="base or options" className={field} value={q.base ?? ""} onChange={(e) => set({ base: e.target.value })}>
          <option value="">every rule set</option>
          <option value="base">base only</option>
          <option value="options">with an option</option>
        </select>
        <select aria-label="TP rule" className={field} value={q.tp_rule ?? ""} onChange={(e) => set({ tp_rule: e.target.value })}>
          <option value="">any TP rule</option>
          <option value=">">TP wider than SL</option>
          <option value="1.5x">TP at least 1.5x SL</option>
          <option value="2x">TP at least 2x SL</option>
          <option value="any">any TP</option>
        </select>
        <select aria-label="days judged" className={field} value={q.window ?? 0} onChange={(e) => set({ window: Number(e.target.value) })}>
          <option value={0}>any window</option>
          {/* the 1-4 day rooms' rule sets (Oct 07, 2026): on by those days, off by 30 */}
          <option value={1}>on by 1 day</option>
          <option value={2}>on by 2 days</option>
          <option value={3}>on by 3 days</option>
          <option value={4}>on by 4 days</option>
          <option value={15}>15 days</option>
          <option value={30}>30 days</option>
        </select>
        <select aria-label="widest stop" className={field} value={q.max_sl ?? 0} onChange={(e) => set({ max_sl: Number(e.target.value) })}>
          <option value={0}>any stop</option>
          <option value={1}>stop 1% or tighter</option>
          <option value={1.5}>stop 1.5% or tighter</option>
          <option value={2}>stop 2% or tighter</option>
        </select>
        <label className="flex items-center gap-1 text-gray-500 dark:text-gray-400">beat random at least
          <input aria-label="beat random at least" className={`${field} w-14`} inputMode="numeric" value={q.min_beat ? String(q.min_beat) : ""}
            onChange={(e) => set({ min_beat: Number(e.target.value.replace(/[^0-9]/g, "")) || 0 })} /> in 100</label>
        <label className="flex items-center gap-1 text-gray-500 dark:text-gray-400">
          <input type="checkbox" checked={!!q.deployable} onChange={(e) => set({ deployable: e.target.checked })} /> a room can run it today</label>
        <input aria-label="find a rule set by id" placeholder="#id" className={`${field} w-24`} value={q.q ?? ""} onChange={(e) => set({ q: e.target.value })} />
        <button type="button" className={btn} onClick={() => setQ({ sort: "rank", page: 1 })}>clear</button>
      </div>
      {err && <p className="mt-2 text-theme-xs text-error-500">could not read the rule sets — {err}</p>}
      {d && (
        <p className="mt-2 text-[11px] text-gray-500 dark:text-gray-400">
          {d.total.toLocaleString()} rule set{d.total === 1 ? "" : "s"}{d.tested ? ` of ${d.tested.total.toLocaleString()} tested` : ""}{d.filters && d.filters.length ? ` · ${d.filters.join(" · ")}` : ""}{d.why ? ` · ${d.why}` : ""}
        </p>
      )}
      {d && d.rows.length > 0 && (
        <div className="mt-2 max-w-full overflow-x-auto">
          <table className="w-full min-w-[1300px] text-theme-xs">
            <thead><tr>
              {["id", "rule set", "this month — backtest (range)", "after the reality check (range)", "trades a month", "won / lost", "win rate", "worst losing run", "most open → money needed", "beat random", "can a room run it"].map((h) => <th key={h} className={th}>{h}</th>)}
            </tr></thead>
            <tbody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
              {d.rows.map((x) => <RuleRow key={x.id} r={x} open={open === x.id} toggle={() => setOpen(open === x.id ? null : x.id)} />)}
            </tbody>
          </table>
        </div>
      )}
      {d && <PageButtons cur={d.page} pages={d.pages} goto={(n) => setQ((x) => ({ ...x, page: n }))} what="rule set" />}
    </div>
  );
}

/** `beforeStreaks`: the sections placed above the Streaks — Backtest a room,
 *  then Room strategies under it (operator, Oct 05, 2026: "put Backtest a
 *  room section above streak section"; Oct 07, 2026: "put room strategies
 *  under backtest a room"). */
export default function ForecastV2({ beforeStreaks }: { beforeStreaks?: ReactNode } = {}) {
  const [s, setS] = useState<F2Summary | null>(null);
  const [err, setErr] = useState("");
  const load = useCallback(() => {
    api.forecastV2().then((r) => { setS(r); setErr(""); }).catch((e) => setErr(String(e?.message ?? e)));
  }, []);
  useLiveRefresh(load, 30_000, [load]);
  const c = s?.chain;
  const without = c?.missing ? Object.entries(c.missing) : [];
  // NO BANNER (operator, Oct 07, 2026: "remove the banner 'Forecast v2' it
  // should be 'run it everyday' enabled in the backend"): the daily run is
  // always on, with no box to untick. What stays is a line ONLY when
  // something is wrong — a failure is still named on the page (CLAUDE.md,
  // "A job that cannot start must SAY SO"); when all is well, nothing shows.
  const trouble = [
    err ? `could not read Forecast v2 — ${err}` : "",
    s?.refresh_error ? `the newest practice numbers ${s.refresh_error}` : "",
    c?.error ? `the daily GitHub run: ${c.error}` : "",
    without.length ? `the daily GitHub run was used without: ${without.map(([step, m]) => `${step} ${m.failed.length} of ${m.of} machines (${m.failed.slice(0, 4).join(", ")}${m.failed.length > 4 ? ", …" : ""})`).join("; ")}` : "",
  ].filter(Boolean);
  return (
    <div className="flex flex-col gap-5">
      {trouble.map((t) => <p key={t} className="text-theme-xs text-error-500">{t}</p>)}
      {beforeStreaks}
      {!s && !err && <p className="text-theme-xs text-gray-400">reading every room&apos;s trade record…</p>}
      {s && (
        <>
          <div className={card}>
            <h3 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">Streaks</h3>
            <p className="mt-1 text-[11px] text-gray-500 dark:text-gray-400">wins (or losses) in a row ending with the most recent closed trade; each coin is named once on the bell when it first reaches one, in at most one bell an hour · practice: {s.streak_counts.practice.win.toLocaleString()} winning and {s.streak_counts.practice.loss.toLocaleString()} losing runs now{s.streak_counts.backtest ? ` · backtest: ${s.streak_counts.backtest.win.toLocaleString()} winning and ${s.streak_counts.backtest.loss.toLocaleString()} losing runs of ${s.streak_counts.backtest.floor}+` : ""}</p>
            <div className="mt-3 grid min-w-0 gap-6 2xl:grid-cols-2 [&>*]:min-w-0">
              <StreakList kind="win" initial={s.defaults.win_n} />
              <StreakList kind="loss" initial={s.defaults.loss_m} />
            </div>
          </div>
          {/* NO "Where the money goes", "What if" OR "This month so far"
              (operator, Oct 08, 2026: "delete Where the money goes section i
              dont need it anymore, delete What if ... as well, delete This
              month so far ... as well") */}
          <Rules s={s} />
        </>
      )}
    </div>
  );
}
