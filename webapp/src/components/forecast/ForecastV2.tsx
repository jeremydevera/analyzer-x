"use client";
/** AUTO TRADE -> FORECAST V2 — which coins are hot, which to stay away from,
 *  what is losing the money, and which room rules will make the most this
 *  month.
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
import { Fragment, useCallback, useState } from "react";
import {
  api, fmtMoney, fmtWhen, fmtWhenMs, F2AvoidPage, F2FamilyPage, F2Group, F2Page, F2Rule, F2RulePage,
  F2RuleQuery, F2Streak, F2StreakPage, F2Summary, F2WhatIf, F2WhatIfCfg,
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
/** the past months a tracker band was measured on, "Jul, Aug and Sep 2026" —
 *  read off the rows, never a literal (label-must-match-data) */
const pastMonths = (rows: { so_far: { months: string[] } | null }[]) => {
  const keys = rows.find((r) => r.so_far?.months?.length)?.so_far?.months ?? [];
  if (!keys.length) return "past months";
  const names = keys.map(monthName);
  const oneYear = new Set(keys.map((k) => k.slice(0, 4))).size === 1;
  const shown = oneYear ? [...names.slice(0, -1).map((n) => n.slice(0, 3)), names[names.length - 1]] : names;
  return shown.length === 1 ? shown[0] : `${shown.slice(0, -1).join(", ")} and ${shown[shown.length - 1]}`;
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

// -------------------------------------------------------- B. coins to avoid
function Avoid({ s }: { s: F2Summary }) {
  // TEN A PAGE FROM THE SERVER (Oct 02, 2026: "make it paginated just like
  // in auto trade") — the whole list used to sit in one scroll box
  const [page, setPage] = useState(1);
  const [d, setD] = useState<F2AvoidPage | null>(null);
  const [err, setErr] = useState("");
  const load = useCallback(() => {
    api.forecastV2Avoid(page).then((r) => { setD(r); setErr(""); })
      .catch((e) => setErr(String(e?.message ?? e)));
  }, [page]);
  useLiveRefresh(load, 30_000, [load]);
  const rows = d?.rows ?? [];
  return (
    <div className={card}>
      <h3 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">Coins to avoid</h3>
      {err && <p className="mt-1 text-theme-xs text-error-500">could not read the coins to avoid — {err}</p>}
      {d && (
        <p className="mt-1 text-[11px] text-gray-500 dark:text-gray-400">
          {d.total.toLocaleString()} of {d.examined.toLocaleString()} coins traded in practice {d.rule} · the backtest column is the same strategies&apos; last 30 days
        </p>
      )}
      {d && (rows.length ? (
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-theme-xs">
            <thead><tr>{["coin", "rooms", "trades", "won / lost", "win rate", "profit", "worst losing run", "backtest win rate"].map((h) => <th key={h} className={th}>{h}</th>)}</tr></thead>
            <tbody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
              {rows.map((c) => (
                <tr key={c.coin}>
                  <td className={`${td} font-semibold`}>{c.coin}</td>
                  <td className={td}>{c.rooms.length} ({c.rooms.map(roomName).join(", ")})</td>
                  <td className={td}>{c.trades}</td>
                  <td className={td}>{c.wins} / {c.losses}</td>
                  <td className={td}>{pct(c.winrate)}</td>
                  <td className={`${td} ${tone(c.profit)}`}>{fmtMoney(c.profit)}</td>
                  <td className={`${td} text-error-500`}>{fmtMoney(c.worst_run)} over {c.worst_run_trades}</td>
                  <td className={td}>{c.backtest.trades ? `${pct(c.backtest.winrate)} of ${c.backtest.trades.toLocaleString()}` : "not rebuilt yet"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <p className="mt-2 text-theme-xs text-gray-400">no coin has lost money over {s.defaults.avoid_min_trades}+ practice trades in the {d.examined} coins examined</p>)}
      {d && <PageButtons cur={d.page} pages={d.pages} goto={setPage} what="coins to avoid" />}
    </div>
  );
}

// --------------------------------------------------- C. where the money goes
// the small splits only — the signal families are summed by the server and
// paged there (Families)
function sumBreakdown(s: F2Summary, key: "tf" | "kind" | "hour" | "stops") {
  const out: Record<string, [number, number, number]> = {};
  const rooms = s.backtest?.rooms ?? {};
  for (const r of Object.values(rooms)) {
    for (const [k, v] of Object.entries(r[key] ?? {})) {
      const c = out[k] ?? [0, 0, 0];
      out[k] = [c[0] + v[0], c[1] + v[1], c[2] + v[2]];
    }
  }
  return out;
}

function SideBySide({ title, rows, bt, note, backtest }: {
  title: string; rows: F2Group[]; bt: Record<string, [number, number, number]>; note?: string;
  /** whether any backtest exists — a paged list cannot tell from its own rows */
  backtest?: boolean;
}) {
  const hasBt = backtest ?? Object.keys(bt).length > 0;
  return (
    <div>
      <p className="text-theme-xs font-medium text-gray-700 dark:text-gray-300">{title}</p>
      {note && <p className="text-[10px] text-gray-400">{note}</p>}
      <div className="overflow-x-auto">
        <table className="mt-1 w-full text-theme-xs">
          <thead><tr>
            <th className={th}></th><th className={th}>practice</th><th className={th}>win rate</th><th className={th}>profit</th>
            <th className={th}>backtest</th><th className={th}>win rate</th><th className={th}>profit</th>
          </tr></thead>
          <tbody>
            {rows.map((g) => {
              const b = bt[g.group];
              return (
                <tr key={g.group}>
                  <td className={`${td} font-medium`}>{g.group}{g.thin && <span className="ml-1 text-[10px] text-gray-400">(too few trades)</span>}</td>
                  <td className={td}>{g.trades.toLocaleString()}</td>
                  <td className={td}>{pct(g.winrate)}</td>
                  <td className={`${td} ${tone(g.profit)}`}>{fmtMoney(g.profit)}</td>
                  <td className={td}>{b ? b[0].toLocaleString() : hasBt ? "0" : "—"}</td>
                  <td className={td}>{b && b[0] ? pct((100 * b[1]) / b[0]) : "—"}</td>
                  <td className={`${td} ${tone(b ? b[2] : null)}`}>{b ? fmtMoney(b[2]) : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Money({ s }: { s: F2Summary }) {
  const m = s.money;
  const z = m.sizes;
  const btNote = s.backtest ? "backtest = the rooms' own rules replayed over their last 30 days" : "backtest: not measured yet";
  return (
    <div className={card}>
      <h3 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">Where the money goes</h3>
      <p className="mt-1 text-[11px] text-gray-500 dark:text-gray-400">practice trades of every room, split every way; a row under {m.thin_below} trades is marked as too few to mean anything · {btNote}</p>
      <div className="mt-3 grid gap-4 lg:grid-cols-2 [&>*]:min-w-0">
        <div>
          <p className="text-theme-xs font-medium text-gray-700 dark:text-gray-300">Costs: fees, spread and funding</p>
          <p className="text-theme-xs text-gray-600 dark:text-gray-300">All rooms made <b className={tone(m.costs.profit)}>{fmtMoney(m.costs.profit)}</b>; costs took {fmtMoney(-m.costs.costs)} of it — without costs it would be <span className={tone(m.costs.without_costs)}>{fmtMoney(m.costs.without_costs)}</span>.</p>
          <div className="overflow-x-auto">
            <table className="mt-1 w-full text-theme-xs">
              <thead><tr>{["room", "trades", "profit", "costs", "without costs", "worst day"].map((h) => <th key={h} className={th}>{h}</th>)}</tr></thead>
              <tbody>{m.costs.rooms.map((r) => (
                <tr key={r.room}>
                  <td className={`${td} font-medium`}>{r.name}{r.retired && <span className="text-[10px] text-gray-400"> (off)</span>}</td>
                  <td className={td}>{r.trades.toLocaleString()}</td>
                  <td className={`${td} ${tone(r.profit)}`}>{fmtMoney(r.profit)}</td>
                  <td className={td}>{fmtMoney(-r.costs)}</td>
                  <td className={`${td} ${tone(r.without_costs)}`}>{fmtMoney(r.without_costs)}</td>
                  <td className={`${td} ${tone(r.worst_day?.profit)}`}>{r.worst_day ? `${fmtMoney(r.worst_day.profit)} · the day from ${fmtWhen(r.worst_day.at)}` : "—"}</td>
                </tr>))}
              </tbody>
            </table>
          </div>
        </div>
        <div className="flex flex-col gap-2">
          <p className="text-theme-xs font-medium text-gray-700 dark:text-gray-300">A win against a loss</p>
          <p className="text-theme-xs text-gray-600 dark:text-gray-300">
            An average win paid <b className="text-success-600">{fmtMoney(z.avg_win)}</b> and an average loss cost <b className="text-error-500">{fmtMoney(z.avg_loss)}</b>, so the rooms need {pct(z.break_even)} wins to break even — they won {pct(z.winrate)} ({z.wins.toLocaleString()} of {z.trades.toLocaleString()}).
          </p>
          <p className="text-theme-xs font-medium text-gray-700 dark:text-gray-300">One coin in many rooms right now</p>
          <p className="text-[10px] text-gray-400">with real money MEXC merges a coin into ONE position across rooms</p>
          <div className="flex flex-wrap gap-1">
            {m.overlap.slice(0, 12).map((o) => (
              <Badge key={o.coin} kind={o.flag ? "bad" : "info"}>{o.coin} · {o.count} room{o.count === 1 ? "" : "s"}</Badge>
            ))}
            {!m.overlap.length && <span className="text-theme-xs text-gray-400">no practice trade open right now</span>}
          </div>
        </div>
        <SideBySide title="By timeframe" rows={m.by_tf} bt={sumBreakdown(s, "tf")} />
        <SideBySide title="Stocks or crypto" rows={m.by_kind} bt={sumBreakdown(s, "kind")} />
        <SideBySide title="By the hour it opened (New York time)" rows={m.by_hour} bt={sumBreakdown(s, "hour")} />
        <SideBySide title="Stop-outs: how long a losing trade lasted" rows={m.stop_outs} bt={sumBreakdown(s, "stops")}
          note="practice: trades closed by their stop · backtest: every losing trade" />
        <Families />
      </div>
    </div>
  );
}

/** By signal family, worst first: EVERY family, ten a page from the server
 *  (it used to show the 15 that lost the most and nothing else), each row
 *  with the rooms' backtest the server summed beside it. */
function Families() {
  const [page, setPage] = useState(1);
  const [d, setD] = useState<F2FamilyPage | null>(null);
  const [err, setErr] = useState("");
  const load = useCallback(() => {
    api.forecastV2Families(page).then((r) => { setD(r); setErr(""); })
      .catch((e) => setErr(String(e?.message ?? e)));
  }, [page]);
  useLiveRefresh(load, 30_000, [load]);
  const bt: Record<string, [number, number, number]> = {};
  for (const g of d?.rows ?? []) if (g.bt) bt[g.group] = g.bt;
  return (
    <div className="lg:col-span-2">
      {err && <p className="text-theme-xs text-error-500">could not read the signal families — {err}</p>}
      {d && <SideBySide title="By signal family (worst first)" rows={d.rows} bt={bt} backtest={d.has_backtest}
        note={`${d.total.toLocaleString()} families traded, worst first`} />}
      {d && <PageButtons cur={d.page} pages={d.pages} goto={setPage} what="signal family" />}
    </div>
  );
}

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
          <option value={0}>15 or 30 days</option>
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
      <WhatIf s={s} />
    </div>
  );
}

function WhatIf({ s }: { s: F2Summary }) {
  const [cfg, setCfg] = useState<F2WhatIfCfg>({ window_days: 30, on_winrate: 90, min_trades: 40, tp_rule: ">", max_sl: 2 });
  const [note, setNote] = useState("");
  // every what-if asked, newest first, ten a page from the server (it used to
  // send the newest 20 and nothing older)
  const [page, setPage] = useState(1);
  const [asked, setAsked] = useState<F2Page<F2WhatIf> | null>(null);
  const load = useCallback(() => {
    api.forecastV2WhatIfs(page).then(setAsked).catch(() => { /* the list is a convenience */ });
  }, [page]);
  useLiveRefresh(load, 30_000, [load]);
  const rows = asked?.rows ?? [];
  const ask = async () => {
    setNote("asking…");
    try {
      const got = await api.forecastV2WhatIf(cfg);
      // the server's own words for where the run is — a queued run behind the
      // daily replay can wait an hour, so no fixed estimate is printed here
      setNote(got.status === "done" ? `#${got.id} is measured — below`
        : got.status === "working" ? `#${got.id}: ${got.why}` : `#${got.id} ${got.status}: ${got.why}`);
      // the newest is on page 1; moving there loads it, and only one request
      // is in flight, so an older page's answer cannot land on top of it
      if (page === 1) load(); else setPage(1);
    } catch (e) { setNote(`not asked — ${String((e as Error)?.message ?? e)}`); }
  };
  const opt = (key: string, value: unknown) => setCfg((c) => {
    const next = { ...c } as Record<string, unknown>;
    if (next[key] === value) delete next[key]; else next[key] = value;
    return next as F2WhatIfCfg;
  });
  return (
    <div className="mt-4 rounded-xl border border-dashed border-gray-300 p-3 dark:border-gray-700">
      <p className="text-theme-xs font-medium text-gray-700 dark:text-gray-300">What if — type any rules and see the same prediction</p>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-theme-xs">
        <label className="flex items-center gap-1">win rate <input aria-label="what-if win rate" className={`${field} w-14`} value={cfg.on_winrate} onChange={(e) => setCfg({ ...cfg, on_winrate: Number(e.target.value.replace(/[^0-9.]/g, "")) || 0 })} />%</label>
        <label className="flex items-center gap-1">trades <input aria-label="what-if trades" className={`${field} w-14`} value={cfg.min_trades} onChange={(e) => setCfg({ ...cfg, min_trades: Number(e.target.value.replace(/[^0-9]/g, "")) || 0 })} /></label>
        <select aria-label="what-if days" className={field} value={cfg.window_days} onChange={(e) => setCfg({ ...cfg, window_days: Number(e.target.value) })}>
          <option value={15}>judged on 15 days</option><option value={30}>judged on 30 days</option>
        </select>
        <select aria-label="what-if TP rule" className={field} value={cfg.tp_rule} onChange={(e) => setCfg({ ...cfg, tp_rule: e.target.value })}>
          <option value=">">TP wider than SL</option><option value="1.5x">TP at least 1.5x SL</option><option value="2x">TP at least 2x SL</option><option value="any">any TP</option>
        </select>
        <label className="flex items-center gap-1">stop at most <input aria-label="what-if stop" className={`${field} w-14`} value={cfg.max_sl} onChange={(e) => setCfg({ ...cfg, max_sl: Number(e.target.value.replace(/[^0-9.]/g, "")) || 0 })} />%</label>
      </div>
      <div className="mt-2 flex flex-wrap gap-2 text-theme-xs">
        {s.options.filter((o) => o.key !== "only_tf" && o.key !== "coin_slices" && o.key !== "max_cost" && o.key !== "day_loss" && o.key !== "kind").map((o) => (
          <label key={`${o.key}-${String(o.value)}`} className="flex items-center gap-1 text-gray-600 dark:text-gray-300">
            <input type="checkbox" checked={(cfg as Record<string, unknown>)[o.key] === o.value} onChange={() => opt(o.key, o.value)} /> {o.words}
          </label>
        ))}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <button type="button" onClick={ask} disabled={!s.backtest}
          className="rounded-lg bg-brand-500 px-4 py-1.5 text-theme-xs font-medium text-white hover:bg-brand-600 disabled:opacity-50">predict these rules</button>
        {note && <span className="text-theme-xs text-gray-600 dark:text-gray-300">{note}</span>}
        {!s.backtest && <span className="text-theme-xs text-gray-400">needs the first daily run first</span>}
      </div>
      {asked && asked.total > 0 && (
        <p className="mt-2 text-[11px] text-gray-500 dark:text-gray-400">{asked.total.toLocaleString()} asked, newest first</p>
      )}
      {rows.length > 0 && (
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-theme-xs">
            <thead><tr>{["asked", "rule set", "status", "measured on", "this month after the reality check", "backtest says"].map((h) => <th key={h} className={th}>{h}</th>)}</tr></thead>
            <tbody>{rows.map((w) => (
              <tr key={w.id}>
                <td className={td}>{w.asked_at ? fmtWhen(w.asked_at) : "—"}</td>
                <td className="py-1.5 pr-3 text-gray-700 dark:text-gray-300">#{w.id} {w.words}</td>
                {/* a run with an id says where it is in its own words — "working —
                    waiting in GitHub's queue, not started yet" read as two answers */}
                <td className={td}>{w.status === "working" && w.why ? w.why : `${w.status}${w.why ? ` — ${w.why}` : ""}`}</td>
                {/* WHICH DATA (bug hunt, round 13): after a daily run the table is
                    measured on a newer replay than an older what-if */}
                <td className={td}>{w.end_ms ? `data to ${fmtWhenMs(w.end_ms)}` : "—"}{w.end_ms && s.backtest && w.end_ms !== s.backtest.data.end_ms ? " — older than the table's; ask again to measure it on the newest" : ""}</td>
                <td className={`${td} ${tone(w.result?.predicted?.corrected)}`}>{w.result ? corrRange(w.result.predicted) : "—"}</td>
                <td className={td}>{w.result ? range(w.result.predicted) : "—"}</td>
              </tr>))}
            </tbody>
          </table>
        </div>
      )}
      {asked && <PageButtons cur={asked.page} pages={asked.pages} goto={setPage} what="what-if" />}
    </div>
  );
}

function Tracker({ s }: { s: F2Summary }) {
  const t = s.tracker;
  if (!t) return null;
  return (
    <div className={card}>
      <h3 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">This month so far — {monthName(t.month)}, day {t.day} of {t.days}</h3>
      <p className="mt-1 text-[11px] text-gray-500 dark:text-gray-400">each room&apos;s practice month against what its own rules made by the end of day {t.day} of {pastMonths(t.rooms)} in the backtest; the bell rings once a month if a room falls under the worst of those after the reality check</p>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-theme-xs">
          <thead><tr>{["room", "its rules", "made so far", "trades", `by the end of day ${t.day} (after the reality check)`, `by the end of day ${t.day} (backtest)`].map((h) => <th key={h} className={th}>{h}</th>)}</tr></thead>
          <tbody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
            {t.rooms.map((r) => (
              <tr key={r.room}>
                <td className={`${td} font-semibold`}>{r.name}{r.below && <span className="ml-1"><Badge kind="bad">under its worst case</Badge></span>}</td>
                <td className="py-1.5 pr-3 text-gray-600 dark:text-gray-300">{r.id ? `#${r.id}` : "not in the newest run"}</td>
                <td className={`${td} font-semibold ${tone(r.month.profit)}`}>{fmtMoney(r.month.profit)}</td>
                <td className={td}>{r.month.trades.toLocaleString()} ({r.month.wins} won)</td>
                <td className={td}>{r.so_far && r.so_far.corrected != null ? `${fmtMoney(r.so_far.corrected)} (${fmtMoney(r.so_far.corrected_low)} to ${fmtMoney(r.so_far.corrected_high)})` : "—"}</td>
                <td className={td}>{r.so_far ? `${fmtMoney(r.so_far.profit)} (${fmtMoney(r.so_far.low)} to ${fmtMoney(r.so_far.high)})` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {t.tops.length > 0 && (
        <p className="mt-2 text-[11px] text-gray-500 dark:text-gray-400">
          The 5 best rule sets this month in the backtest: {t.tops.map((x) => `#${x.id} ${x.month ? fmtMoney(x.month.profit) : "not in the data yet"}`).join(" · ")}
        </p>
      )}
      {s.grading && s.grading.months.length > 0 && (
        <div className="mt-3">
          <p className="text-theme-xs font-medium text-gray-700 dark:text-gray-300">Past predictions, graded</p>
          <ul className="mt-1 text-theme-xs text-gray-600 dark:text-gray-300">
            {s.grading.months.map((g) => (
              <li key={g.month}>{monthName(g.month)} (made {fmtWhen(g.made_at)}): {g.graded ? `the backtest landed inside its range ${g.inside} of ${g.judged} times` : g.why}
                {g.differs && g.universe && g.now ? ` · predicted over ${g.universe.groups?.length ?? "?"} signal groups and ${(g.universe.coins ?? 0).toLocaleString()} coins, the newest data covers ${g.now.groups?.length ?? "?"} and ${(g.now.coins ?? 0).toLocaleString()}` : ""}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default function ForecastV2() {
  const [s, setS] = useState<F2Summary | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => {
    api.forecastV2().then((r) => { setS(r); setErr(""); }).catch((e) => setErr(String(e?.message ?? e)));
  }, []);
  useLiveRefresh(load, 30_000, [load]);
  const toggle = async (on: boolean) => {
    setBusy(true);
    try { await api.forecastV2Switch(on); load(); } finally { setBusy(false); }
  };
  const c = s?.chain;
  return (
    <div className="flex flex-col gap-5">
      <div className={card}>
        <h3 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">Forecast v2</h3>
        <p className="mt-1 text-theme-xs text-gray-500 dark:text-gray-400">
          Which coins are on a streak, which to stay away from, what is losing the money, and which room rules should make the most this month —
          from every room&apos;s practice trades (live) and a replay of every strategy on GitHub (once a day). A note only: nothing here switches a room on or off.
        </p>
        {err && <p className="mt-2 text-theme-xs text-error-500">could not read Forecast v2 — {err}</p>}
        {!s && !err && <p className="mt-2 text-theme-xs text-gray-400">reading every room&apos;s trade record…</p>}
        {s && (
          <div className="mt-2 flex flex-col gap-1 text-[11px] text-gray-500 dark:text-gray-400">
            <p>practice numbers read {fmtWhen(s.at)} in {s.took_ms.toLocaleString()} ms{s.refresh_error ? ` · the newest ${s.refresh_error}` : ""}</p>
            <p>
              daily GitHub run: {c?.on === false ? "switched off" : c?.why || "waiting"}{c?.error ? ` · last error: ${c.error}` : ""}
              {c?.missing && Object.keys(c.missing).length > 0 && ` · used without: ${Object.entries(c.missing).map(([step, m]) => `${step} ${m.failed.length} of ${m.of} machines (${m.failed.slice(0, 4).join(", ")}${m.failed.length > 4 ? ", …" : ""})`).join("; ")}`}
              <label className="ml-2 inline-flex items-center gap-1">
                <input type="checkbox" checked={c?.on !== false} disabled={busy} onChange={(e) => toggle(e.target.checked)} /> run it every day
              </label>
            </p>
          </div>
        )}
      </div>
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
          <Avoid s={s} />
          <Money s={s} />
          <Rules s={s} />
          <Tracker s={s} />
        </>
      )}
    </div>
  );
}
