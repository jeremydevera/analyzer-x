"use client";
/** AUTO TRADE -> FORECAST — which trading room is doing best, and why.
 *
 * Operator, Oct 01, 2026: *"create a forecast tab ..."*, then *"go run this /
 * Build ALL 15 Forecast features on Auto Trade -> Forecast, and make sure
 * there is no bug"*. Every number on this screen is worked out on the server
 * by tradingagents/room_stats.py — the ONE place the definitions live, shared
 * with the saved forecasts and the automatic daily one. This file only PRINTS
 * them, so the screen can never disagree with a forecast it is showing.
 *
 * Live (re-read every 15 seconds): the room cards, the answer now. Saved:
 * every forecast, newest first, ten a page, each with what its pick REALLY did
 * since — paged and checked by the server, never filtered here.
 */
import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { api, dateBoxAt, dateBoxValue, fmtMoney, fmtWhen, fmtWhenMs, Forecast, Forecasts, ForecastsLive, RoomGroup, RoomNow, RoomReplay, RoomStrategies, RoomStrategyTrades, RRDay, RREvent, RRSide, RRTrade } from "@/lib/api";
import { useLiveRefresh } from "@/lib/live";
import PageButtons from "@/components/common/PageButtons";
import DayPicker from "@/components/form/DayPicker";
import { Modal } from "@/components/ui/modal";

const roomName = (id: string) => (id === "main" ? "Main" : `#${id}`);
const pct = (v: number | null | undefined) => (v == null ? "—" : `${v.toFixed(1)}%`);
const tone = (v: number | null | undefined) =>
  v == null ? "text-gray-500 dark:text-gray-400" : v >= 0 ? "text-success-600" : "text-error-500";
const card = "rounded-2xl border border-gray-200 bg-white p-5 dark:border-white/[0.05] dark:bg-white/[0.03]";
const btn = "rounded-lg border border-gray-300 px-3 py-1 text-theme-xs text-gray-600 dark:border-gray-700 dark:text-gray-300";

async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) { await navigator.clipboard.writeText(text); return true; }
  } catch { /* fall through to the selection route */ }
  try {
    // over plain http (the Tailscale address) there is no async clipboard
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.top = "-1000px";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return ok;
  } catch { return false; }
}

function PromptBox({ title, text }: { title: string; text: string }) {
  const [state, setState] = useState<"" | "ok" | "fail">("");
  const [open, setOpen] = useState(false);
  const copy = async () => {
    setState((await copyText(text)) ? "ok" : "fail");
    window.setTimeout(() => setState(""), 1500);
  };
  return (
    <div className="rounded-xl border border-gray-200 p-3 dark:border-gray-700">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-theme-sm font-medium text-gray-800 dark:text-white/90">{title}</p>
        <button type="button" onClick={copy}
          className="ml-auto rounded-lg bg-brand-500 px-3 py-1 text-theme-xs font-medium text-white hover:bg-brand-600">
          {state === "ok" ? "copied" : state === "fail" ? "could not copy — select it below" : "copy prompt"}
        </button>
        <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className={btn}>
          {open ? "hide" : "show"}
        </button>
      </div>
      {open && (
        <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap rounded-lg bg-gray-50 p-3 text-[11px] text-gray-700 dark:bg-white/[0.03] dark:text-gray-300">{text}</pre>
      )}
    </div>
  );
}

const VERDICT: Record<Forecast["verdict"], string> = {
  "pick": "best room picked",
  "too early": "too early to tell",
  "none proven": "none is proven yet",
};
const SOURCE: Record<string, string> = {
  prompt: "made by the forecast prompt", button: "made with the button", auto: "made automatically",
};

/** PROFIT OVER TIME (feature 5): the running total, one point per day from the
 *  room's first trade to today, drawn to scale — the vertical scale always
 *  includes $0 so a loss and a gain sit on the same ruler. */
function ProfitLine({ daily }: { daily: RoomNow["daily"] }) {
  if (!daily.length) return <p className="text-[11px] text-gray-400">no closed trade yet, so no line</p>;
  const W = 320, H = 96, L = 46, R = 8, T = 8, B = 16;
  const vals = daily.map((d) => d.total);
  const hi = Math.max(0, ...vals), lo = Math.min(0, ...vals);
  const span = hi - lo || 1;
  const x = (i: number) => (daily.length === 1 ? (L + W - R) / 2 : L + (i * (W - R - L)) / (daily.length - 1));
  const y = (v: number) => T + ((hi - v) * (H - T - B)) / span;
  const pts = daily.map((d, i) => `${x(i).toFixed(1)},${y(d.total).toFixed(1)}`).join(" ");
  const last = daily[daily.length - 1];
  return (
    <figure className="mt-2">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-24 w-full" role="img"
        aria-label={`running profit by day, now ${fmtMoney(last.total)}`}>
        <line x1={L} x2={W - R} y1={y(0)} y2={y(0)} strokeDasharray="3 3"
          className="stroke-gray-300 dark:stroke-gray-600" strokeWidth={1} />
        <text x={L - 4} y={y(hi) + 3} textAnchor="end" className="fill-gray-400 text-[9px]">{fmtMoney(hi)}</text>
        {lo < 0 && <text x={L - 4} y={y(lo) + 3} textAnchor="end" className="fill-gray-400 text-[9px]">{fmtMoney(lo)}</text>}
        {hi > 0 && lo < 0 && <text x={L - 4} y={y(0) + 3} textAnchor="end" className="fill-gray-400 text-[9px]">0</text>}
        <polyline points={pts} fill="none" strokeWidth={2}
          className={last.total >= 0 ? "stroke-success-500" : "stroke-error-500"} />
        {daily.map((d, i) => (
          <circle key={d.day} cx={x(i)} cy={y(d.total)} r={3}
            className={d.total >= 0 ? "fill-success-500" : "fill-error-500"}>
            <title>{`the day starting ${fmtWhen(d.at)}: ${fmtMoney(d.profit)} that day, ${fmtMoney(d.total)} in total`}</title>
          </circle>
        ))}
      </svg>
      <figcaption className="text-[10px] text-gray-400">
        running total, {daily.length} day{daily.length === 1 ? "" : "s"} from {fmtWhen(daily[0].at)} to now
      </figcaption>
    </figure>
  );
}

function Badge({ kind, children }: { kind: "good" | "bad" | "info"; children: React.ReactNode }) {
  const c = kind === "good" ? "bg-success-50 text-success-600 dark:bg-success-500/15"
    : kind === "bad" ? "bg-error-50 text-error-600 dark:bg-error-500/15"
    : "bg-gray-100 text-gray-600 dark:bg-white/[0.06] dark:text-gray-300";
  return <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${c}`}>{children}</span>;
}

function Group({ label, g }: { label: string; g: RoomGroup }) {
  return (
    <tr>
      <td className="py-1 pr-2 text-gray-600 dark:text-gray-300">{label}</td>
      <td className="whitespace-nowrap py-1 pr-2 text-gray-600 dark:text-gray-300">{g.trades.toLocaleString()}</td>
      <td className="whitespace-nowrap py-1 pr-2 text-gray-600 dark:text-gray-300">{g.trades ? `${g.wins} / ${g.losses}` : "—"}</td>
      <td className="whitespace-nowrap py-1 pr-2 text-gray-600 dark:text-gray-300">{pct(g.winrate)}</td>
      <td className={`whitespace-nowrap py-1 pr-2 font-medium ${tone(g.trades ? g.profit : null)}`}>{g.trades ? fmtMoney(g.profit) : "—"}</td>
      <td className={`whitespace-nowrap py-1 ${tone(g.per_trade)}`}>{fmtMoney(g.per_trade)}</td>
    </tr>
  );
}

function RoomCard({ r, rules }: { r: RoomNow; rules: ForecastsLive["rules"] }) {
  const [more, setMore] = useState(false);
  const p = r.practice;
  const res = r.research;
  const resPer = res && res.closed ? res.profit / res.closed : null;
  return (
    <div className={`${card} flex flex-col gap-2 ${r.retired ? "opacity-80" : ""}`}>
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">{r.name}</p>
        {r.retired && <Badge kind="info">turned off · shown to compare</Badge>}
        {p.too_early && <Badge kind="info">too early to tell</Badge>}
        {r.ready.ok && <Badge kind="good">ready for real money</Badge>}
        {r.turn_off.ok && <Badge kind="bad">should be turned off</Badge>}
      </div>
      <p className="text-[11px] text-gray-400">{r.rules}</p>

      {/* the money first, then the line that decides it: break-even */}
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <span className={`text-2xl font-semibold tabular-nums ${tone(p.closed ? p.profit : null)}`}>{p.closed ? fmtMoney(p.profit) : "—"}</span>
        <span className={`text-theme-sm ${tone(p.per_trade)}`}>{fmtMoney(p.per_trade)} a trade</span>
        <span className="text-theme-xs text-gray-500 dark:text-gray-400">
          {p.closed.toLocaleString()} closed ({p.wins.toLocaleString()} won, {p.losses.toLocaleString()} lost)
          · {p.open.toLocaleString()} open · {p.days == null ? "not started" : `${p.days.toFixed(1)} days`}
        </span>
      </div>
      <p className="text-theme-xs">
        <span className={p.vs_breakeven == null ? "text-gray-600 dark:text-gray-300" : tone(p.vs_breakeven)}>{pct(p.winrate)} wins</span>
        {p.breakeven != null ? (
          <span className="text-gray-600 dark:text-gray-300">
            {` · needs ${pct(p.breakeven)} to break even · `}
            <b className={tone(p.vs_breakeven)}>
              {p.vs_breakeven! >= 0 ? `${p.vs_breakeven!.toFixed(1)} above` : `${Math.abs(p.vs_breakeven!).toFixed(1)} short`}
            </b>
          </span>
        ) : (
          <span className="text-gray-500 dark:text-gray-400">{` · break-even: ${p.breakeven_why}`}</span>
        )}
      </p>
      {p.too_early && (
        <p className="text-[11px] text-gray-400">too early to tell: {p.too_early_why.join(" and ")} (needs {rules.too_early_trades} trades and {rules.too_early_days} days)</p>
      )}

      {r.alarms.length > 0 && (
        <ul className="flex flex-col gap-1">
          {r.alarms.map((a) => (
            <li key={a.kind} className="rounded-lg bg-error-50 px-3 py-1.5 text-theme-xs text-error-600 dark:bg-error-500/10 dark:text-error-400">⚠ {a.text}</li>
          ))}
        </ul>
      )}
      {r.turn_off.ok && <p className="rounded-lg bg-warning-50 px-3 py-1.5 text-theme-xs text-warning-700 dark:bg-warning-500/10 dark:text-warning-400">Should be turned off: {r.turn_off.why}. A note only — nothing is switched off.</p>}

      <dl className="grid grid-cols-1 gap-x-4 gap-y-1 text-theme-xs sm:grid-cols-2">
        <div><dt className="text-gray-400">worst losing run</dt>
          <dd className="text-gray-700 dark:text-gray-300">{p.worst_run_trades ? `${fmtMoney(p.worst_run)} over ${p.worst_run_trades} trades` : "none yet"}
            {res && <span className="text-gray-400"> · research {fmtMoney(res.worst_run)} over {res.worst_run_trades}</span>}</dd></div>
        <div><dt className="text-gray-400">worst case today</dt>
          <dd className={tone(r.worst_case.up_to)}>{r.worst_case.open
            ? `up to ${fmtMoney(r.worst_case.up_to)} if all ${r.worst_case.open.toLocaleString()} open trades hit their stop now`
            : r.worst_case.unpriced ? "" : "no open trade"}
            {r.worst_case.unpriced > 0 && <span className="text-gray-400">{r.worst_case.open ? " · " : ""}{r.worst_case.unpriced.toLocaleString()} open trade(s) with no stop to price are not in it</span>}</dd></div>
        <div><dt className="text-gray-400">costs</dt>
          <dd className="text-gray-700 dark:text-gray-300">
            {r.costs.matched ? <>{fmtMoney(-r.costs.total)} in total, {fmtMoney(r.costs.per_trade == null ? null : -r.costs.per_trade)} a trade · <span className={tone(r.costs.without_costs)}>{fmtMoney(r.costs.without_costs)} without costs</span>
              {r.costs.matched < r.costs.of && <span className="text-gray-400"> ({r.costs.matched} of {r.costs.of} trades matched to their opening)</span>}</> : "no closed trade yet"}
          </dd></div>
        <div><dt className="text-gray-400">September research</dt>
          <dd className="text-gray-700 dark:text-gray-300">{res
            ? <>{fmtMoney(res.profit)} · {fmtMoney(resPer)} a trade · {pct(res.winrate)} wins · most open {res.max_open.toLocaleString()}</>
            : "not in this research"}</dd></div>
        {(r.real.trades > 0 || r.real.open > 0) && (
          <div className="sm:col-span-2"><dt className="text-gray-400">real money (counted on its own)</dt>
            <dd className="text-gray-700 dark:text-gray-300">{r.real.trades.toLocaleString()} closed, {r.real.wins} won, <span className={tone(r.real.profit)}>{fmtMoney(r.real.profit)}</span> · {r.real.open.toLocaleString()} open</dd></div>
        )}
      </dl>

      <ProfitLine daily={r.daily} />
      {r.unreadable_lines > 0 && (
        <p className="text-[10px] text-warning-700 dark:text-warning-400">{r.unreadable_lines.toLocaleString()} line(s) of this room&apos;s trade record could not be read and are not counted</p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={() => setMore(!more)} aria-expanded={more} className={btn}>
          {more ? "hide details" : "market hours, worst coins, readiness"}
        </button>
      </div>
      {more && (
        <div className="flex flex-col gap-3">
          <div>
            <p className="text-theme-xs font-medium text-gray-700 dark:text-gray-300">Stock coins: while their market was open, and while it was closed</p>
            <p className="text-[10px] text-gray-400">stock coin = {r.hours.rule}; split by {r.hours.split_by}, Monday–Friday (holidays not taken out){r.hours.listed_abroad != null && `; ${r.hours.listed_abroad.toLocaleString()} stock coins listed outside the US are on this project's list, and any other is timed as a New York stock`} · {r.hours.stock_trades.toLocaleString()} stock trades, {r.hours.other_trades.toLocaleString()} other trades not counted here</p>
            {/* no minimum width: at 390px a forced 420 hid "profit" and "a trade" off the side */}
            <div className="overflow-x-auto">
              <table className="mt-1 w-full text-theme-xs">
                <thead><tr className="text-start text-gray-400">
                  {["when it opened", "trades", "won / lost", "win rate", "profit", "a trade"].map((h) => <th key={h} className="py-1 pr-2 text-start font-medium">{h}</th>)}
                </tr></thead>
                <tbody>
                  {(r.hours.markets ?? []).map((m) => (
                    <Fragment key={m.market}>
                      <Group label={`${m.market} · open (${m.hours})`} g={m.open} />
                      <Group label={`${m.market} · closed (nights and weekends)`} g={m.closed} />
                    </Fragment>
                  ))}
                  {(r.hours.unlisted?.trades ?? 0) > 0 && (
                    <Group label={`not on any market yet (${(r.hours.unlisted_coins ?? []).join(", ")})`} g={r.hours.unlisted!} />
                  )}
                  {r.hours.stock_trades === 0 && (
                    <tr><td colSpan={6} className="py-1 text-gray-400">no closed stock-coin trade yet</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
          <div>
            <p className="text-theme-xs font-medium text-gray-700 dark:text-gray-300">The coins losing the most</p>
            {r.losers.length ? (
              <div className="overflow-x-auto">
                <table className="mt-1 w-full text-theme-xs">
                  <thead><tr className="text-start text-gray-400">
                    {["coin", "trades", "won / lost", "profit"].map((h) => <th key={h} className="py-1 pr-2 text-start font-medium">{h}</th>)}
                  </tr></thead>
                  <tbody>
                    {r.losers.map((l) => (
                      <tr key={l.coin}>
                        <td className="py-1 pr-2 font-medium text-gray-700 dark:text-gray-300">{l.coin}</td>
                        <td className="whitespace-nowrap py-1 pr-2 text-gray-600 dark:text-gray-300">{l.trades}</td>
                        <td className="whitespace-nowrap py-1 pr-2 text-gray-600 dark:text-gray-300">{l.wins} / {l.losses}</td>
                        <td className="whitespace-nowrap py-1 text-error-500">{fmtMoney(l.profit)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <p className="text-[11px] text-gray-400">no coin has lost money overall in {p.closed.toLocaleString()} closed trades</p>}
          </div>
          <div>
            <p className="text-theme-xs font-medium text-gray-700 dark:text-gray-300">Ready for real money?</p>
            <p className="text-[11px] text-gray-500 dark:text-gray-400">{r.ready.ok
              ? "yes — every rule below is met. A badge only: real money is still switched on only by you."
              : `not yet — still needs ${r.ready.missing.join("; ")}`}</p>
            <p className="text-[10px] text-gray-400">rules: {rules.ready_trades}+ closed trades, {rules.ready_days}+ days, wins above break-even, losing run no worse than its research</p>
          </div>
          <p className="text-[10px] text-gray-400">costs = {rules.cost_note}</p>
        </div>
      )}
    </div>
  );
}

function SinceCell({ f }: { f: Forecast }) {
  if (!f.pick) return <span className="text-gray-400">no pick</span>;
  const s = f.since;
  if (!s) return <span className="text-gray-400">—</span>;
  const label = s.result === "right" ? "right" : s.result === "wrong" ? "wrong" : "too early";
  return (
    <span>
      <span className={tone(s.trades ? s.profit : null)}>{fmtMoney(s.profit)}</span>
      <span className="text-gray-400"> over {s.trades.toLocaleString()} trades in {s.days.toFixed(1)} days · </span>
      <b className={s.result === "right" ? "text-success-600" : s.result === "wrong" ? "text-error-500" : "text-gray-500"}>{label}</b>
    </span>
  );
}

function ForecastDetail({ f }: { f: Forecast }) {
  const rooms = [...f.rooms].sort((a, b) => (b.real.per_trade ?? -1e9) - (a.real.per_trade ?? -1e9));
  return (
    // no scroll box of its own: it sits in a full-width row of the list's
    // table, so ONE sideways scroll moves both on a phone
    <div className="mt-1">
      {f.note && <p className="text-[11px] text-gray-400">{f.note}</p>}
      {f.artifact && <a href={f.artifact} target="_blank" rel="noreferrer" className="text-theme-xs text-brand-500 hover:underline">full table ↗</a>}
      <table className="w-full min-w-[760px] text-theme-xs">
        <thead>
          <tr className="text-start text-gray-500 dark:text-gray-400">
            {["room", "profit then", "won / lost", "win rate", "break-even", "a trade",
              "worst losing run", "open", "days", "research"].map((h) => (
              <th key={h} className="px-2 py-1.5 text-start font-medium">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 text-gray-700 dark:divide-white/[0.05] dark:text-gray-300">
          {rooms.map((r) => (
            <tr key={r.id} className={f.pick === r.id ? "bg-success-50/60 dark:bg-success-500/10" : ""}>
              <td className="px-2 py-1.5">
                <span className="font-semibold text-gray-800 dark:text-white/90">{roomName(r.id)}</span>
                {r.retired && <span className="ml-1 text-[10px] text-gray-400">(turned off)</span>}
              </td>
              <td className={`px-2 py-1.5 font-semibold ${tone(r.real.closed ? r.real.profit : null)}`}>{fmtMoney(r.real.profit)}</td>
              <td className="px-2 py-1.5 text-gray-600 dark:text-gray-300">{r.real.wins.toLocaleString()} / {r.real.losses.toLocaleString()}</td>
              <td className="px-2 py-1.5 text-gray-600 dark:text-gray-300">{pct(r.real.winrate)}</td>
              <td className="px-2 py-1.5 text-gray-500 dark:text-gray-400">{pct(r.real.breakeven)}</td>
              <td className={`px-2 py-1.5 ${tone(r.real.per_trade)}`}>{fmtMoney(r.real.per_trade)}</td>
              <td className="px-2 py-1.5 text-error-500">{r.real.worst_run_trades ? `${fmtMoney(r.real.worst_run)} over ${r.real.worst_run_trades}` : "—"}</td>
              <td className="px-2 py-1.5 text-gray-600 dark:text-gray-300">{r.real.open.toLocaleString()}</td>
              <td className="px-2 py-1.5 text-gray-600 dark:text-gray-300">{r.real.days.toFixed(1)}</td>
              <td className="px-2 py-1.5 text-gray-500 dark:text-gray-400">{r.research?.profit != null ? fmtMoney(r.research.profit) : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function History({ d, setPage }: { d: Forecasts; setPage: (n: number) => void }) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <div className={card}>
      <h3 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">Saved forecasts</h3>
      <p className="mt-1 text-theme-xs text-gray-500 dark:text-gray-400">
        {d.total
          ? <>{d.total.toLocaleString()} saved · page {d.page} of {d.pages} · {d.score.judged
            ? <b className="text-gray-700 dark:text-gray-200">picks right {d.score.right} of {d.score.judged}</b>
            : `no pick can be judged yet (${d.score.with_pick} of ${d.score.saved} named a room; a pick is judged after 100 trades and 7 days)`}</>
          : "No forecast saved yet — press “make a new forecast now”, or copy prompt 1 into Claude."}
        {d.unreadable ? ` · ${d.unreadable.toLocaleString()} saved line(s) could not be read` : ""}
      </p>
      {d.forecasts.length > 0 && (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[720px] text-theme-xs">
            <thead>
              <tr className="text-start text-gray-500 dark:text-gray-400">
                {["made", "verdict", "why", "the pick since then"].map((h) => (
                  <th key={h} className="px-2 py-1.5 text-start font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 text-gray-700 dark:divide-white/[0.05] dark:text-gray-300">
              {d.forecasts.map((f, i) => (
                <Fragment key={`${f.at}-${i}`}>
                  <tr className="align-top">
                    {/* the button sits in the FIRST column: at 390px the last
                        column of a 720px table is off the side of the screen */}
                    <td className="whitespace-nowrap px-2 py-1.5 text-gray-600 dark:text-gray-300">
                      {fmtWhen(f.at)}
                      <span className="block text-[10px] text-gray-400">{SOURCE[f.source ?? "prompt"] ?? f.source}</span>
                      <button type="button" onClick={() => setOpen(open === i ? null : i)} aria-expanded={open === i} className={`${btn} mt-1`}>
                        {open === i ? "hide rooms" : "rooms then"}
                      </button>
                    </td>
                    <td className="px-2 py-1.5"><Badge kind={f.verdict === "pick" ? "good" : "info"}>{VERDICT[f.verdict]}{f.pick ? `: ${roomName(f.pick)}` : ""}</Badge></td>
                    <td className="px-2 py-1.5 text-gray-600 dark:text-gray-300">{f.pick_why}</td>
                    <td className="px-2 py-1.5"><SinceCell f={f} /></td>
                  </tr>
                  {open === i && (
                    <tr>
                      <td colSpan={4} className="px-2 pb-3"><ForecastDetail f={f} /></td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {/* newest first: page 1 is the newest ten */}
      <PageButtons cur={d.page} pages={d.pages} goto={(n) => { setPage(n); setOpen(null); }} what="saved forecasts" />
    </div>
  );
}

export default function RoomForecasts() {
  const [live, setLive] = useState<ForecastsLive | null>(null);
  const [liveErr, setLiveErr] = useState("");
  const [d, setD] = useState<Forecasts | null>(null);
  const [err, setErr] = useState("");
  const [page, setPage] = useState(1);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");

  const loadLive = useCallback(() => {
    api.forecastsLive().then((r) => { setLive(r); setLiveErr(""); })
      .catch((e) => setLiveErr(String(e?.message ?? e)));
  }, []);
  const loadSaved = useCallback(() => {
    api.forecasts(page).then((r) => { setD(r); setErr(""); })
      .catch((e) => setErr(String(e?.message ?? e)));
  }, [page]);
  useLiveRefresh(loadLive, 15_000, [loadLive]);
  useLiveRefresh(loadSaved, 30_000, [loadSaved]);

  const makeNow = async () => {
    setBusy(true); setNote("");
    try {
      const got = await api.forecastNew();
      setNote(`saved a new forecast at ${fmtWhen(got.saved.at)}: ${VERDICT[got.saved.verdict]}${got.saved.pick ? ` — ${roomName(got.saved.pick)}` : ""}`);
      setPage(1);
      loadSaved();
    } catch (e) {
      setNote(`not saved — ${String((e as Error)?.message ?? e)}`);
    } finally { setBusy(false); }
  };

  const v = live?.verdict;
  return (
    <div className="flex flex-col gap-5">
      <div className={card}>
        <h3 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">Room forecasts</h3>
        <p className="mt-1 text-theme-xs text-gray-500 dark:text-gray-400">
          Which trading room is doing best, from its real practice trades (practice money, $5 a trade at 20x —
          $100 of coin). A room is judged only once it has {live?.rules.too_early_trades ?? 100} closed trades
          and {live?.rules.too_early_days ?? 7} days; until then it is “too early to tell”.
        </p>
        {liveErr && <p className="mt-3 text-theme-xs text-error-500">could not read the rooms — {liveErr}</p>}
        {!live && !liveErr && <p className="mt-3 text-theme-xs text-gray-400">reading every room’s trade record…</p>}
        {v && (
          <div className={`mt-4 rounded-xl border p-4 ${v.verdict === "pick" ? "border-success-500" : "border-gray-200 dark:border-gray-700"}`}>
            <p className="text-theme-xs uppercase tracking-wide text-gray-400">the answer now</p>
            <p className="mt-1 text-lg font-semibold text-gray-800 dark:text-white/90">
              {v.verdict === "pick" ? `${roomName(v.pick!)} is the best room` : v.verdict === "too early" ? "Too early to tell" : "None is proven yet"}
            </p>
            <p className="mt-1 text-theme-sm text-gray-600 dark:text-gray-300">{v.pick_why}</p>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <button type="button" onClick={makeNow} disabled={busy}
                className="rounded-lg bg-brand-500 px-4 py-2 text-theme-sm font-medium text-white hover:bg-brand-600 disabled:opacity-50">
                {busy ? "saving…" : "make a new forecast now"}
              </button>
              {note && <span className="text-theme-xs text-gray-600 dark:text-gray-300">{note}</span>}
            </div>
            <p className="mt-2 text-[11px] text-gray-400">
              automatic forecast, once a day after the daily GitHub update is on this PC: {d?.auto.why || "checked every 30 seconds by the site"}
              {d?.auto.error ? ` · last error: ${d.auto.error}` : ""}
            </p>
            <p className="mt-1 text-[10px] text-gray-400">
              numbers read {fmtWhen(live.at)} in {live.took_ms.toLocaleString()} ms · refreshed every 15 seconds
              {live.research.graded_from ? ` · research: graded ${live.research.graded_from} to ${live.research.graded_to}` : ""}
            </p>
            {live.refresh_error && (
              <p className="mt-1 text-[11px] text-error-500">the newest numbers {live.refresh_error} — these are from {fmtWhen(live.at)}</p>
            )}
          </div>
        )}
      </div>

      {live && <RoomTable rooms={live.rooms} rules={live.rules} />}
      {live && <RoomBacktestPanel rooms={live.rooms} />}

      {err && <p className="text-theme-xs text-error-500">could not read the saved forecasts — {err}</p>}
      {d && <History d={d} setPage={setPage} />}

      {d && (
        <div className={card}>
          <h3 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">Forecast prompts</h3>
          <p className="mt-1 text-theme-xs text-gray-500 dark:text-gray-400">
            Prompt 1 makes a written forecast in Claude and saves it here; prompt 2 checks every saved forecast against what happened since.
          </p>
          <div className="mt-3 grid items-start gap-3 lg:grid-cols-2">
            {d.prompts.map((p) => <PromptBox key={p.title} title={p.title} text={p.text} />)}
          </div>
        </div>
      )}
    </div>
  );
}

/** THE ROOMS AS ONE TABLE (operator, Oct 02, 2026: "also make the room tiles
 *  in table instead so its not confusing"). One row per room, the numbers that
 *  decide it side by side; a click opens that room's full card under its row,
 *  so nothing the cards said is lost. */
function RoomTable({ rooms, rules }: { rooms: RoomNow[]; rules: ForecastsLive["rules"] }) {
  const [open, setOpen] = useState<string | null>(null);
  const th = "px-2 py-1.5 text-start font-medium whitespace-nowrap";
  const td = "px-2 py-1.5 whitespace-nowrap";
  return (
    <div className={card}>
      <h3 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">Rooms</h3>
      <p className="mt-1 text-theme-xs text-gray-500 dark:text-gray-400">
        Practice money, $5 a trade at 20x ($100 of coin). Click a room for its full details.
      </p>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[960px] text-theme-xs">
          <thead>
            <tr className="border-b border-gray-200 text-gray-500 dark:border-gray-700 dark:text-gray-400">
              {["Room", "Profit", "A trade", "Closed", "Won / lost", "Win rate", "Needs to break even",
                "Open", "Days", "Worst losing run", "Worst case today", "September research"].map((h) => (
                <th key={h} className={th}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 text-gray-700 dark:divide-white/[0.05] dark:text-gray-300">
            {rooms.map((r) => {
              const p = r.practice;
              const res = r.research;
              return (
                <Fragment key={r.id}>
                  <tr onClick={() => setOpen(open === r.id ? null : r.id)} aria-expanded={open === r.id}
                    className={`cursor-pointer hover:bg-gray-50 dark:hover:bg-white/[0.03] ${r.retired ? "opacity-70" : ""}`}>
                    <td className="min-w-[200px] max-w-[260px] px-2 py-1.5">
                      <span className="font-semibold text-gray-800 dark:text-white/90">{r.name}</span>
                      <span className="mt-0.5 flex flex-wrap gap-1">
                        {r.retired && <Badge kind="info">turned off</Badge>}
                        {p.too_early && <Badge kind="info">too early</Badge>}
                        {r.ready.ok && <Badge kind="good">ready for real money</Badge>}
                        {r.turn_off.ok && <Badge kind="bad">should be turned off</Badge>}
                        {r.alarms.length > 0 && <Badge kind="bad">⚠ {r.alarms.length}</Badge>}
                      </span>
                    </td>
                    <td className={`${td} font-semibold ${tone(p.closed ? p.profit : null)}`}>{p.closed ? fmtMoney(p.profit) : "—"}</td>
                    <td className={`${td} ${tone(p.per_trade)}`}>{fmtMoney(p.per_trade)}</td>
                    <td className={td}>{p.closed.toLocaleString()}</td>
                    <td className={td}>{p.wins.toLocaleString()} / {p.losses.toLocaleString()}</td>
                    <td className={`${td} ${p.vs_breakeven == null ? "" : tone(p.vs_breakeven)}`}>{pct(p.winrate)}</td>
                    <td className={td}>{p.breakeven != null
                      ? <>{pct(p.breakeven)} <b className={tone(p.vs_breakeven)}>({p.vs_breakeven! >= 0 ? `${p.vs_breakeven!.toFixed(1)} above` : `${Math.abs(p.vs_breakeven!).toFixed(1)} short`})</b></>
                      : <span className="text-gray-400">—</span>}</td>
                    <td className={td}>{p.open.toLocaleString()}</td>
                    <td className={td}>{p.days == null ? "—" : p.days.toFixed(1)}</td>
                    <td className={td}>{p.worst_run_trades ? `${fmtMoney(p.worst_run)} over ${p.worst_run_trades}` : "—"}</td>
                    <td className={`${td} ${tone(r.worst_case.up_to)}`}>{r.worst_case.open ? fmtMoney(r.worst_case.up_to) : "—"}</td>
                    <td className={td}>{res ? <>{fmtMoney(res.profit)} · {pct(res.winrate)}</> : <span className="text-gray-400">not in it</span>}</td>
                  </tr>
                  {open === r.id && (
                    <tr><td colSpan={12} className="bg-gray-50 p-3 dark:bg-white/[0.02]">
                      <RoomCard r={r} rules={rules} />
                    </td></tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** a date input's value as the local midnight it names, in seconds */
const dayStart = (v: string) => Date.parse(`${v}T00:00:00`) / 1000;

/** BACKTEST A ROOM = REPLAY ITS OWN RULES, DAY BY DAY (operator, Oct 02, 2026:
 *  "backtest room should like backtest for the room strategy example / what
 *  strategies did switched on and off for Sept 3, 4, 5, 6, 7 and so on"; spec
 *  docs/superpowers/specs/2026-10-02-room-replay-design.md). The room's own
 *  watcher rules walk the days; every strategy's own Backtest v2 trade list
 *  decides and pays; the practice account's real trades sit beside it. The
 *  replay is measured in its own process (tradingagents/room_replay.py) and
 *  every list here is paged by the server, ten a page. */
function dayOf(ms: number) {
  const m = fmtWhenMs(ms).match(/^(.*\d{4})\s/);       // "Sep 03, 2026" of "Sep 03, 2026 12:00am"
  return m ? m[1] : fmtWhenMs(ms);
}

const RR_STATE: Record<string, string> = {
  measuring: "Being measured", busy: "Waiting for another replay", waiting: "Waiting for the disk",
  failed: "The last run failed", not_measured: "Not measured yet",
};

/** How far a replay run has got (operator, Oct 03, 2026: "can you show
 *  loading bar on whats percentage so i know the progress, in mobile i only
 *  see 'being measured' only"). Every word and number comes from the run's
 *  own status (room_replay.PHASES): a step with a count shows its percent, a
 *  step without one says so and its bar moves without a number. */
function RunProgress({ run }: { run: NonNullable<RoomReplay["run"]> }) {
  const pct = run.pct;
  const mins = run.elapsed_s != null ? Math.floor(run.elapsed_s / 60) : null;
  return (
    <div className="mt-2">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <span>{run.step && run.steps ? `Step ${run.step} of ${run.steps}: ` : ""}{run.step_words ?? run.phase ?? "starting"}</span>
        <span className="font-semibold text-gray-800 dark:text-white/90">
          {pct != null ? `${pct.toFixed(0)}%` : "no count for this step"}
        </span>
      </div>
      <div className="mt-1 h-2.5 w-full overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700"
        role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct ?? undefined}
        aria-label="replay progress">
        {pct != null
          ? <div className="h-full rounded-full bg-brand-500 transition-all" style={{ width: `${pct}%` }} />
          : <div className="h-full w-1/3 animate-pulse rounded-full bg-brand-500/60" />}
      </div>
      <div className="mt-1 flex flex-wrap justify-between gap-x-3 text-[11px] text-gray-500 dark:text-gray-400">
        <span>{run.total ? `${(run.done ?? 0).toLocaleString()} of ${run.total.toLocaleString()}` : ""}</span>
        <span>{mins != null ? `running for ${mins < 1 ? "under a minute" : `${mins} min`}` : ""}</span>
      </div>
    </div>
  );
}

/** THE ROOM PICKER WITH A SEARCH BOX INSIDE ITS LIST (operator, Oct 05,
 *  2026: "in the room dropdown, i want able to have search bar inside the
 *  dropdown tab"). Typing narrows the rooms by name or by their rules
 *  ("6B08", "15 days", "80%"); Enter picks the first match, Escape or a
 *  click outside closes it. The list is every room the page was sent — it is
 *  never a page cut by a server, so filtering it here is filtering the data. */
function RoomPicker({ rooms, value, onChange }: {
  rooms: RoomNow[]; value: string; onChange: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  // OPENS UPWARD when the page has no room below it (operator, Oct 05, 2026:
  // "the dropdown is on bottom part of the screen i cannot click it") — the
  // panel sits last on the page, so a list opening down ran off the screen
  const [up, setUp] = useState(false);
  const [q, setQ] = useState("");
  const box = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!open) return;
    input.current?.focus();
    const away = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);
  const words = q.trim().toLowerCase().replace(/^#/, "");
  const shown = rooms.filter((r) => !words
    || `${r.name} ${r.id} ${r.rules ?? ""}`.toLowerCase().includes(words));
  const pick = (id: string) => { onChange(id); setOpen(false); setQ(""); };
  const cur = rooms.find((r) => r.id === value);
  return (
    <div ref={box} className="relative">
      <button type="button" aria-haspopup="listbox" aria-expanded={open} aria-label="room"
        onClick={() => {
          const r = box.current?.getBoundingClientRect();
          // the list is a search box plus up to 15rem of rooms: ~320px
          setUp(!!r && window.innerHeight - r.bottom < 340 && r.top > window.innerHeight - r.bottom);
          setOpen(!open);
        }}
        className="flex min-w-[9rem] items-center justify-between gap-2 rounded-lg border border-gray-300 bg-transparent px-2 py-1 text-theme-xs text-gray-700 dark:border-gray-700 dark:text-gray-300">
        <span>{cur?.name ?? value}</span><span aria-hidden className="text-gray-400">▾</span>
      </button>
      {open && (
        <div className={`absolute left-0 z-50 w-64 max-w-[calc(100vw-2rem)] rounded-lg border border-gray-200 bg-white p-2 shadow-lg dark:border-gray-700 dark:bg-gray-900 ${up ? "bottom-full mb-1" : "top-full mt-1"}`}>
          <input ref={input} value={q} onChange={(e) => setQ(e.target.value)} placeholder="search rooms"
            aria-label="search rooms"
            onKeyDown={(e) => {
              if (e.key === "Escape") setOpen(false);
              if (e.key === "Enter" && shown[0]) pick(shown[0].id);
            }}
            className="w-full rounded-md border border-gray-300 bg-transparent px-2 py-1 text-theme-xs text-gray-700 dark:border-gray-700 dark:text-gray-200" />
          <ul role="listbox" aria-label="rooms" className="mt-1 max-h-60 overflow-auto">
            {shown.map((r) => (
              <li key={r.id} role="option" aria-selected={r.id === value}>
                <button type="button" onClick={() => pick(r.id)}
                  className={`block w-full rounded-md px-2 py-1 text-start text-theme-xs hover:bg-gray-100 dark:hover:bg-white/[0.06] ${r.id === value ? "font-semibold text-brand-600 dark:text-brand-400" : "text-gray-700 dark:text-gray-300"}`}>
                  {r.name}
                  {r.rules && <span className="block text-[10px] font-normal text-gray-400">{r.rules}</span>}
                </button>
              </li>
            ))}
            {!shown.length && (
              <li className="px-2 py-1 text-theme-xs text-gray-400">no room matches &ldquo;{q}&rdquo; — {rooms.length} rooms in all</li>
            )}
          </ul>
        </div>
      )}
    </div>
  );
}

function RoomBacktestPanel({ rooms }: { rooms: RoomNow[] }) {
  const live = rooms.filter((r) => !r.retired);
  const [room, setRoom] = useState(live[0]?.id ?? "main");
  const [from, setFrom] = useState(dateBoxValue(32));
  const [to, setTo] = useState(dateBoxValue(1));
  const [asked, setAsked] = useState<{ room: string; from: string; to: string } | null>(null);
  const [page, setPage] = useState(1);
  const [day, setDay] = useState("");
  const [evPage, setEvPage] = useState(1);
  const [trPage, setTrPage] = useState(1);
  const [d, setD] = useState<RoomReplay | null>(null);
  const [ev, setEv] = useState<RoomReplay | null>(null);
  const [tr, setTr] = useState<RoomReplay | null>(null);
  const [err, setErr] = useState("");
  // THE DAYS THEMSELVES go to the server, never seconds worked out here: a
  // browser in another time zone than this PC turned Oct 01 into Sep 30
  // (Oct 05, 2026: "10/01/2026 to 10/04/2026" was measured as 2026-09-30 to
  // 2026-10-04)
  const base = asked && { room: asked.room, from_day: asked.from, to_day: asked.to };
  // set the moment Replay is pressed, cleared by the first answer: the bar and
  // the greyed button show at once (operator, Oct 05, 2026: "when i click
  // replay, immediately show me loading bar and disable the replay button")
  const [starting, setStarting] = useState(false);
  const running = starting || !!d?.run?.running;
  const load = useCallback(() => {
    if (!base) return;
    api.roomReplay({ ...base, view: "days", page })
      .then((x) => { setD(x); setErr(""); })
      .catch((e) => setErr(String(e?.message ?? e)))
      .finally(() => setStarting(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [asked, page]);
  // every 3 seconds while a run is measuring, so the bar moves; 15 otherwise
  useLiveRefresh(load, running ? 3_000 : 15_000, [load, running]);
  const loadDay = useCallback(() => {
    if (!base || !day) return;
    api.roomReplay({ ...base, view: "events", day, page: evPage, }).then(setEv).catch(() => {});
    api.roomReplay({ ...base, view: "trades", day, page: trPage }).then(setTr).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [asked, day, evPage, trPage]);
  useLiveRefresh(loadDay, 60_000, [loadDay]);
  const go = () => {
    setPage(1); setDay(""); setEv(null); setTr(null); setD(null); setErr("");
    setStarting(true);
    setAsked({ room, from, to });
  };
  const again = () => base && api.roomReplay({ ...base, view: "days", page: 1, refresh: true })
    .then(setD).catch((e) => setErr(String(e?.message ?? e)));
  const name = (id: string) => rooms.find((r) => r.id === id)?.name ?? id;
  const sel = "rounded-lg border border-gray-300 bg-transparent px-2 py-1 text-theme-xs text-gray-700 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-300 dark:[color-scheme:dark]";
  const th = "px-2 py-1.5 text-start font-medium whitespace-nowrap";
  const td = "px-2 py-1.5 whitespace-nowrap";
  const c = d?.cfg;
  const s = d?.summary;
  const side = (label: string, x: RRSide | undefined) => x && (
    <tr>
      <td className={`${td} font-medium text-gray-700 dark:text-gray-300`}>{label}</td>
      <td className={`${td} font-semibold ${tone(x.closed ? x.profit : null)}`}>{x.closed ? fmtMoney(x.profit) : "—"}</td>
      <td className={td}>{c ? `${c.tp_rule === ">" ? "wider than SL" : c.tp_rule}` : "—"}</td>
      <td className={td}>{c ? `${c.max_sl}% or tighter` : "—"}</td>
      <td className={td}>{d?.leverage ?? 20}x</td>
      <td className={td}>{x.closed.toLocaleString()}</td>
      <td className={td}>{x.wins.toLocaleString()} / {x.losses.toLocaleString()}</td>
      <td className={td}>{pct(x.winrate)}</td>
      <td className={td}>{x.worst_streak_trades ? `${fmtMoney(x.worst_streak)} over ${x.worst_streak_trades}` : "—"}</td>
    </tr>
  );
  const days = (d?.state === "ready" ? d.rows : []) as RRDay[];
  // the room's own start lies inside the range: compare over its hours only
  const roomStarted = !!(s?.backtest_room_hours?.from_ms && d?.start_ms
    && s.backtest_room_hours.from_ms > d.start_ms);
  return (
    <div className={card}>
      <h3 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">Backtest a room</h3>
      <p className="mt-1 text-theme-xs text-gray-500 dark:text-gray-400">
        The room&apos;s own rules replayed day by day: which strategies they would have switched on and off each day,
        and what those strategies&apos; own Backtest v2 trades made while on — beside what the practice account really did.
        Click a day for its switches and its trades.
      </p>
      <div className="mt-3 flex flex-wrap items-end gap-2 text-theme-xs text-gray-600 dark:text-gray-300">
        <div className="flex flex-col gap-1">room
          <RoomPicker rooms={live} value={room} onChange={setRoom} />
        </div>
        <div className="flex flex-col gap-1">from
          <DayPicker label="from" className={`${sel} w-32`} value={from} max={to} onChange={setFrom} />
        </div>
        <div className="flex flex-col gap-1">to
          <DayPicker label="to" className={`${sel} w-32`} value={to} min={from} onChange={setTo} />
        </div>
        <button type="button" disabled={!from || !to || running} onClick={go}
          className="rounded-lg bg-brand-500 px-4 py-1.5 font-medium text-white hover:bg-brand-600 disabled:cursor-not-allowed disabled:opacity-50">
          {running ? "Replaying…" : "Replay"}
        </button>
      </div>
      {starting && !d && asked && (
        <div className="mt-3 rounded-xl border border-gray-200 p-3 text-theme-xs text-gray-600 dark:border-gray-700 dark:text-gray-300">
          <b>Starting</b> — {name(asked.room)} {dayOf(dayStart(asked.from) * 1000)} to {dayOf(dayStart(asked.to) * 1000)}
          <RunProgress run={{ running: true, step: 1, steps: 7, step_words: "starting up", pct: null }} />
        </div>
      )}
      {err && <p className="mt-3 text-theme-xs text-error-500">could not read the replay — {err}</p>}
      {d && d.state !== "ready" && (
        <div className="mt-3 rounded-xl border border-gray-200 p-3 text-theme-xs text-gray-600 dark:border-gray-700 dark:text-gray-300">
          <b>{RR_STATE[d.state] ?? d.state}</b> — {name(d.room)} {dayOf(dayStart(d.from_day) * 1000)} to {dayOf(dayStart(d.to_day) * 1000)}
          {d.state === "measuring" && d.run?.running ? <RunProgress run={d.run} /> : <>: {d.why}</>}
          {/* busy: ANOTHER range is measuring — its own bar, named by its dates */}
          {d.state === "busy" && d.run?.running && <RunProgress run={d.run} />}
          {d.state === "failed" && (
            <button type="button" className={`${btn} ml-2`} onClick={again}>measure it again</button>
          )}
          <span className="block text-[10px] text-gray-400">checked again every 15 seconds</span>
        </div>
      )}
      {d?.state === "ready" && s && c && (
        <>
          <p className="mt-3 text-theme-xs text-gray-500 dark:text-gray-400">
            {name(d.room)} · {d.start_ms ? dayOf(d.start_ms) : d.from_day} to {d.end_ms ? dayOf(d.end_ms) : d.to_day} · its rules: switch on at {c.on_winrate}%+ over the last {c.window_days} day{c.window_days === 1 ? "" : "s"},
            off under {c.off_winrate}%{c.judge_days && c.judge_days !== c.window_days ? ` over the last ${c.judge_days} days` : ""}, {c.min_trades}+ trades, TP wider than SL, stop {c.max_sl}% or tighter ·
            ${d.margin} a trade at {d.leverage}x (${(d.margin ?? 5) * (d.leverage ?? 20)} of coin) ·
            {" "}{(d.candidates?.count ?? 0).toLocaleString()} strategies tested
            {d.candidates?.min_wr30 != null
              ? ` (${(d.candidates.searched ?? d.candidates.count).toLocaleString()} with a 30-day win rate of ${d.candidates.min_wr30}% or more`
                + `${d.candidates.room_picks?.added ? `, plus ${d.candidates.room_picks.added.toLocaleString()} the room switched on itself` : ""})`
              : ""} ·
            {" "}{s.backtest.switched_on.toLocaleString()} switched on, {s.backtest.switched_off.toLocaleString()} off · measured {d.computed_at ? fmtWhen(d.computed_at) : "—"}
            {d.run?.running ? " · being measured again" : ""}
            <button type="button" className={`${btn} ml-2`} onClick={again}>measure again</button>
          </p>
          {/* THE HINDSIGHT NOTE GOES BESIDE THE TOTALS, never under the
              tables: it changes how every total reads (Oct 03, 2026,
              #6B08FF64: replay +6,947.20, practice -13.24) */}
          {d.notes?.[0]?.startsWith("HINDSIGHT") && (
            <p className="mt-2 rounded-xl border border-warning-300 bg-warning-50 p-3 text-theme-xs text-warning-700 dark:border-warning-500/30 dark:bg-warning-500/10 dark:text-warning-400">
              {d.notes[0]}
            </p>
          )}
          <div className="mt-2 overflow-x-auto">
            <table className="w-full min-w-[820px] text-theme-xs">
              <thead><tr className="border-b border-gray-200 text-gray-500 dark:border-gray-700 dark:text-gray-400">
                {["", "Profit", "TP", "SL", "Lev", "Trades", "Won / lost", "Win rate", "Worst losing run"].map((h) => <th key={h} className={th}>{h}</th>)}
              </tr></thead>
              <tbody className="divide-y divide-gray-100 text-gray-700 dark:divide-white/[0.05] dark:text-gray-300">
                {/* THE ROOM'S OWN HOURS FIRST (Oct 05, 2026: "practice has 191 trades
                    and your replay has 435" — 320 of them were before the room
                    started): backtest and practice over the same hours, then
                    what the rules alone did before the room existed */}
                {roomStarted
                  ? side(`Backtest, while your room ran (from ${fmtWhenMs(s.backtest_room_hours!.from_ms!)})`, s.backtest_room_hours)
                  : side("Backtest", s.backtest)}
                {side(`Practice (real, from ${s.practice.from_ms ? fmtWhenMs(s.practice.from_ms) : "—"})`, s.practice)}
                {roomStarted && (s.backtest_before_room?.closed ?? 0) > 0
                  && side(`Backtest before your room started (its rules alone, ${fmtWhenMs(s.backtest_before_room!.from_ms!)} to ${fmtWhenMs(s.backtest_before_room!.to_ms!)}) — nothing to compare`, s.backtest_before_room)}
              </tbody>
            </table>
          </div>
          {s.follow_from_ms && (
            <p className="mt-2 text-theme-xs text-gray-600 dark:text-gray-300">
              From {fmtWhenMs(s.follow_from_ms)} the replay switches on and off only what your room switched, when it switched it
              {s.refused_by_room && s.refused_by_room.closed > 0
                ? <>, and leaves out the {s.refused_by_room.closed.toLocaleString()} trade{s.refused_by_room.closed === 1 ? "" : "s"} your
                  room refused ({Object.entries(s.refused_by_room.by).map(([k, n]) => `${n.toLocaleString()} ${d.reasons?.[k] ?? k}`).join(", ")}),
                  which would have made <span className={tone(s.refused_by_room.profit)}>{fmtMoney(s.refused_by_room.profit)}</span> in the backtest.</>
                : "."}
            </p>
          )}
          {Object.keys(s.reconcile ?? {}).length > 0 && (
            <ul className="mt-2 list-disc pl-5 text-theme-xs text-gray-600 dark:text-gray-300">
              {Object.entries(s.reconcile).filter(([k]) => !k.includes(":")).map(([k, n]) => (
                <li key={k}>{n.toLocaleString()} — {k.replaceAll("_", " ")}
                  {Object.entries(s.reconcile).filter(([k2]) => k2.startsWith(`${k}:`)).map(([k2, n2]) =>
                    ` · ${n2.toLocaleString()} ${d.reasons?.[k2.split(":")[1]] ?? k2.split(":")[1]}`).join("")}</li>
              ))}
            </ul>
          )}
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[1100px] text-theme-xs">
              <thead><tr className="border-b border-gray-200 text-gray-500 dark:border-gray-700 dark:text-gray-400">
                {["Day", "Switched on", "Switched off", "Running", "Trades", "Won / lost", "Win rate", "Profit", "Running total",
                  "Worst losing run", "Practice (trades · profit · total)"].map((h) => <th key={h} className={th}>{h}</th>)}
              </tr></thead>
              <tbody className="divide-y divide-gray-100 text-gray-700 dark:divide-white/[0.05] dark:text-gray-300">
                {days.map((x) => (
                  <tr key={x.day} onClick={() => { setDay(day === x.day ? "" : x.day); setEvPage(1); setTrPage(1); setEv(null); setTr(null); }}
                    aria-expanded={day === x.day}
                    className={`cursor-pointer hover:bg-gray-50 dark:hover:bg-white/[0.03] ${day === x.day ? "bg-gray-50 dark:bg-white/[0.04]" : ""}`}>
                    <td className={`${td} font-medium`}>{dayOf(x.at)}{!x.judged_full && <span className="ml-1 text-[10px] text-gray-400">(fewer than {Math.max(c.window_days, c.judge_days || 0)} days known)</span>}</td>
                    <td className={`${td} ${x.on ? "text-success-600" : ""}`}>{x.on || "—"}</td>
                    <td className={`${td} ${x.off ? "text-error-500" : ""}`}>{x.off || "—"}</td>
                    <td className={td}>{x.running}</td>
                    <td className={td}>{x.closed}</td>
                    <td className={td}>{x.wins} / {x.losses}</td>
                    <td className={td}>{pct(x.winrate)}</td>
                    <td className={`${td} ${tone(x.closed ? x.profit : null)}`}>{x.closed ? fmtMoney(x.profit) : "—"}</td>
                    <td className={`${td} ${tone(x.total)}`}>{fmtMoney(x.total)}</td>
                    <td className={td}>{x.worst_streak_trades ? `${fmtMoney(x.worst_streak)} over ${x.worst_streak_trades}` : "—"}</td>
                    <td className={td}>{x.practice ? <>{x.practice.closed} · <span className={tone(x.practice.profit)}>{fmtMoney(x.practice.profit)}</span> · <span className={tone(x.practice.total)}>{fmtMoney(x.practice.total)}</span></> : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <PageButtons cur={d.page ?? 1} pages={d.pages ?? 1} goto={setPage} what="room backtest" />
          {day && (
            <div className="mt-3 rounded-xl bg-gray-50 p-3 dark:bg-white/[0.03]">
              <p className="text-theme-xs font-medium text-gray-700 dark:text-gray-300">
                {dayOf(days.find((x) => x.day === day)?.at ?? dayStart(day) * 1000)} — {ev?.total ?? 0} switch{ev?.total === 1 ? "" : "es"}, {tr?.total ?? 0} trade{tr?.total === 1 ? "" : "s"} closed
              </p>
              {(ev?.rows?.length ?? 0) > 0 && (
                <div className="mt-2 overflow-x-auto">
                  <table className="w-full min-w-[900px] text-theme-xs">
                    <thead><tr className="text-gray-500 dark:text-gray-400">
                      {["When", "", "Strategy", "TP", "SL", "Why"].map((h) => <th key={h} className={th}>{h}</th>)}
                    </tr></thead>
                    <tbody className="divide-y divide-gray-100 text-gray-700 dark:divide-white/[0.05] dark:text-gray-300">
                      {(ev!.rows as RREvent[]).map((e, i) => (
                        <tr key={`${e.id}-${e.at}-${i}`}>
                          <td className={td}>{fmtWhenMs(e.at)}</td>
                          <td className={`${td} font-semibold ${e.action === "on" ? "text-success-600" : "text-error-500"}`}>{e.action === "on" ? "switched on" : "switched off"}</td>
                          <td className={td}><span className="font-mono">#{e.id}</span> {e.coin} <span className="text-gray-400">{e.tf} {e.signal}</span></td>
                          <td className={td}>{e.tp != null ? `${e.tp}%` : "—"}</td>
                          <td className={td}>{e.sl != null ? `${e.sl}%` : "—"}</td>
                          <td className="px-2 py-1.5 text-gray-600 dark:text-gray-300">{e.why}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <PageButtons cur={ev!.page ?? 1} pages={ev!.pages ?? 1} goto={setEvPage} what="room switches" />
                </div>
              )}
              {(tr?.rows?.length ?? 0) > 0 && (
                <div className="mt-2 overflow-x-auto">
                  <table className="w-full min-w-[900px] text-theme-xs">
                    <thead><tr className="text-gray-500 dark:text-gray-400">
                      {["Opened", "Closed", "Strategy", "Side", "TP", "SL", "Exit", "Profit"].map((h) => <th key={h} className={th}>{h}</th>)}
                    </tr></thead>
                    <tbody className="divide-y divide-gray-100 text-gray-700 dark:divide-white/[0.05] dark:text-gray-300">
                      {(tr!.rows as RRTrade[]).map((t, i) => (
                        <tr key={`${t.id}-${t.entry_ms}-${i}`}>
                          <td className={td}>{fmtWhenMs(t.entry_ms)}</td>
                          <td className={td}>{fmtWhenMs(t.exit_ms)}</td>
                          <td className={td}><span className="font-mono">#{t.id}</span> {t.coin} <span className="text-gray-400">{t.tf} {t.signal}</span></td>
                          <td className={td}>{t.side}</td>
                          <td className={td}>{t.tp}%</td>
                          <td className={td}>{t.sl}%</td>
                          <td className={td}>{t.why}</td>
                          <td className={`${td} ${tone(t.pnl)}`}>{fmtMoney(t.pnl)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <PageButtons cur={tr!.page ?? 1} pages={tr!.pages ?? 1} goto={setTrPage} what="room trades" />
                </div>
              )}
            </div>
          )}
          {(d.notes?.length ?? 0) > 0 && (
            <ul className="mt-3 list-disc pl-5 text-[11px] text-gray-500 dark:text-gray-400">
              {d.notes!.filter((n) => !n.startsWith("HINDSIGHT")).map((n, i) => <li key={i}>{n}</li>)}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

/** BACKTEST A ROOM AND THE ROOMS TABLE, on their own (operator, Oct 02, 2026:
 *  "can i merge forecast to forecast v2 since they are almost the same? ...
 *  what matters to me is this prompt and ability to backtest a room
 *  strategy"). The merged Forecast page (/forecast-v2) shows these under
 *  Forecast v2; this reads the rooms itself so it needs nothing from the page. */
/** BACKTEST A ROOM on its own, reading the rooms itself — placed above the
 *  Streaks on the merged Forecast page (operator, Oct 05, 2026: "put
 *  Backtest a room section above streak section"). */
export function RoomBacktest() {
  const [live, setLive] = useState<ForecastsLive | null>(null);
  const [err, setErr] = useState("");
  const load = useCallback(() => api.forecastsLive()
    .then((d) => { setLive(d); setErr(""); })
    .catch((e) => setErr(String(e?.message ?? e))), []);
  useLiveRefresh(load, 15_000);
  if (err && !live) return <p className="text-theme-xs text-error-500">could not read the rooms — {err}</p>;
  if (!live) return <p className="text-theme-xs text-gray-400">reading every room&apos;s trade record…</p>;
  return <RoomBacktestPanel rooms={live.rooms} />;
}

export function RoomsAndBacktest() {
  const [saved, setSaved] = useState<Forecasts | null>(null);
  // THE PROMPTS WITH THEIR COPY BUTTONS — prompt 4, "Find new winning room
  // strategies", is one of the two things the operator said matter here
  const loadPrompts = useCallback(() => api.forecasts(1).then(setSaved).catch(() => {}), []);
  useLiveRefresh(loadPrompts, 300_000);
  return (
    <>
      {/* ROOM STRATEGIES is no longer here: it sits directly under Backtest a
          room (operator, Oct 07, 2026: "put room strategies under backtest a
          room") — RoomStrategiesSection, handed to ForecastV2 above the Streaks */}
      {saved && saved.prompts.length > 0 && (
        <div className={card}>
          <h3 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">Prompts</h3>
          <p className="mt-1 text-theme-xs text-gray-500 dark:text-gray-400">
            Copy one and paste it to Claude. Prompt 4 finds new winning room strategies and keeps them in Room strategies above.
          </p>
          <div className="mt-3 grid items-start gap-3 lg:grid-cols-2">
            {saved.prompts.map((p) => <PromptBox key={p.title} title={p.title} text={p.text} />)}
          </div>
        </div>
      )}
      {/* BACKTEST A ROOM is no longer here: it sits ABOVE the Streaks on the
          merged page (operator, Oct 05, 2026: "put Backtest a room section
          above streak section") — RoomBacktest, handed to ForecastV2 */}
      {/* NO ROOMS TABLE HERE (operator, Oct 03, 2026 6:30am: "In forecast
          tab remove the rooms section on very bottom i dont need it"); the
          first Forecast page (/forecast) still has it */}
    </>
  );
}

/** ROOM STRATEGIES — every winner prompt 4 kept (operator, Oct 02, 2026: "when
 *  i run that prompt i want you to look for all kinds of combination then add
 *  it in room strategy"). Re-measured on the server over exactly the dates
 *  chosen, from each winner's own stored trades; filtered, sorted and paged
 *  there (tradingagents/room_strategies.table). Never deleted: a winner whose
 *  newest 15 days lost says "stopped working".
 *
 *  NOTHING IS ASKED UNTIL APPLY (operator, Oct 07, 2026: "i want a button to
 *  apply filters on this"). Every box is a draft; Apply (or Enter in any box)
 *  sends them together, and an answer is shown only if it answers what was
 *  last applied — so a list can never sit under a box it does not match. The
 *  two "last 15 days" / "last 30 days" buttons became ONE box ("what i want is
 *  for it to be textbox, if i input 3 days show me the room strat and its
 *  trade for past 3 days"): the last N x 24 hours up to the moment Apply is
 *  pressed. Click a row for its trades in the same dates.
 *
 *  NO "judged on", "a room can run it" OR "sort" (Oct 07, 2026: "remove these
 *  fields its not needed"): one order, the worst month first. And Apply shows
 *  Loading... and cannot be pressed until its answer lands ("when i click
 *  apply, i want to see loading, then make apply button disabled"). */
type RsDraft = { from: string; to: string; days: string; minWin: string; minProfit: string; find: string };
type RsAsk = { from_s: number; to_s: number; days: number | null; min_winrate: number;
  min_profit: number | null; find: string };

const rsDefault = (): RsDraft => ({ from: dateBoxValue(30), to: dateBoxValue(0), days: "", minWin: "",
  minProfit: "", find: "" });

/** The days box: "" = use the dates, a number above 0 = that many days,
 *  anything else = NaN, which Apply refuses out loud. */
function daysOf(v: string): number | null {
  const s = v.trim();
  if (!s) return null;
  const n = Number(s);
  return Number.isFinite(n) && n > 0 && n <= 1000 ? n : NaN;
}

/** Why Apply cannot send these boxes, or null when it can. A box that is
 *  typed in but not a number is refused — never quietly sent as no filter. */
function rsProblem(f: RsDraft): string | null {
  if (Number.isNaN(daysOf(f.days))) return "last N days takes a number of days above 0, like 3";
  if (f.minWin.trim() !== "" && !Number.isFinite(Number(f.minWin))) return "min win % takes a number, like 90";
  if (f.minProfit.trim() !== "" && !Number.isFinite(Number(f.minProfit))) return "min profit $ takes a number, like 5";
  if (daysOf(f.days) === null && (!f.from || !f.to)) return "pick both dates, or type a number of days";
  if (daysOf(f.days) === null && f.from > f.to) return "the 'from' date is after the 'to' date";
  return null;
}

function rsAsk(f: RsDraft, nowS: number): RsAsk {
  const days = daysOf(f.days);
  return {
    from_s: days ? nowS - Math.round(days * 86_400) : dayStart(f.from),
    to_s: days ? nowS : dayStart(f.to) + 86_399,
    days: days || null,
    min_winrate: f.minWin.trim() === "" ? 0 : Number(f.minWin),
    min_profit: f.minProfit.trim() === "" ? null : Number(f.minProfit),
    find: f.find.trim(),
  };
}

/** The filters an answer was asked with, in words, for the line above the
 *  table — the line names what the rows were filtered by, never the boxes. */
function rsFilterWords(a: RsAsk): string[] {
  const out: string[] = [];
  if (a.find) out.push(`id #${a.find.replace(/^#/, "").toUpperCase()}`);
  if (a.min_winrate) out.push(`win rate ${a.min_winrate}% or better`);
  if (a.min_profit != null) out.push(`profit ${fmtMoney(a.min_profit)} or more`);
  return out;
}

const heldFor = (ms: number) => {
  const m = Math.max(0, Math.round(ms / 60_000));
  if (m < 60) return `${m}m`;
  if (m < 1440) return `${Math.floor(m / 60)}h ${m % 60}m`;
  return `${Math.floor(m / 1440)}d ${Math.floor((m % 1440) / 60)}h`;
};

export function RoomStrategiesSection() {
  const [draft, setDraft] = useState<RsDraft>(rsDefault);
  const [applied, setApplied] = useState<{ f: RsDraft; ask: RsAsk }>(() => {
    const f = rsDefault();
    return { f, ask: rsAsk(f, Math.floor(Date.now() / 1000)) };
  });
  const [page, setPage] = useState(1);
  const [shown, setShown] = useState<{ key: string; ask: RsAsk; d: RoomStrategies } | null>(null);
  const [err, setErr] = useState("");
  const [bad, setBad] = useState("");
  // the room strategy whose trades are open in the pop-up
  const [open, setOpen] = useState<{ id: string; words: string } | null>(null);
  // THE ANSWER MUST ANSWER WHAT WAS LAST APPLIED: Oct 07, 2026 3:37pm the
  // boxes said "min win 90" over a list reading "992 of 992 kept" — the page
  // was still showing an answer to an earlier ask (the server answers 2 of
  // 992 for 90%). An answer to anything else is dropped, and until the right
  // one lands Apply says Loading… and cannot be pressed.
  const wantKey = JSON.stringify([applied.ask, page]);
  const want = useRef(wantKey);
  useEffect(() => { want.current = wantKey; }, [wantKey]);
  const load = useCallback(() => {
    const ask = applied.ask;
    const key = JSON.stringify([ask, page]);
    api.roomStrategies({ from_s: ask.from_s, to_s: ask.to_s, min_winrate: ask.min_winrate,
      min_profit: ask.min_profit, find: ask.find, page })
      .then((x) => { if (key === want.current) { setShown({ key, ask, d: x }); setErr(""); } })
      .catch((e) => { if (key === want.current) setErr(String(e?.message ?? e)); });
  }, [applied, page]);
  useLiveRefresh(load, 60_000, [load]);
  const apply = (f: RsDraft = draft) => {
    const why = rsProblem(f);
    setBad(why ?? "");
    if (why) return;
    setApplied({ f, ask: rsAsk(f, Math.floor(Date.now() / 1000)) });
    setPage(1);
    setOpen(null);
  };
  const clear = () => { const f = rsDefault(); setDraft(f); apply(f); };
  const set = (p: Partial<RsDraft>) => setDraft((f) => ({ ...f, ...p }));
  // typing a number of days shows the dates it covers in the date boxes,
  // which wait (greyed) until the days box is emptied again
  const setDays = (v: string) => {
    const n = daysOf(v);
    if (n !== null && !Number.isNaN(n)) {
      const now = Math.floor(Date.now() / 1000);
      set({ days: v, from: dateBoxAt(now - Math.round(n * 86_400)), to: dateBoxAt(now) });
    } else set({ days: v });
  };
  const byDays = daysOf(draft.days) !== null && !Number.isNaN(daysOf(draft.days));
  const unsent = JSON.stringify(draft) !== JSON.stringify(applied.f);
  const waiting = !err && (!shown || shown.key !== wantKey);
  const d = shown?.d ?? null;
  const asked = shown?.ask ?? null;
  const sel = "rounded-lg border border-gray-300 bg-transparent px-2 py-1 text-theme-xs text-gray-700 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-300 dark:[color-scheme:dark]";
  const th = "px-2 py-1.5 text-start font-medium whitespace-nowrap";
  const td = "px-2 py-1.5 whitespace-nowrap";
  const cols = ["ID", "Rules", "Found", "Trades", "A day", "Won / lost", "Win rate", "Break-even", "Profit",
    "After reality check", "Worst day", "Worst losing run", "Most open", "Money needed", "Worst month", "Room can run it"];
  const words = asked ? rsFilterWords(asked) : [];
  const pastEnd = !!(d && d.data_end != null && d.to * 1000 > d.data_end);
  return (
    <div className={card}>
      <h3 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">Room strategies</h3>
      <p className="mt-1 text-theme-xs text-gray-500 dark:text-gray-400">
        Every winner prompt 4 found and kept, never deleted, and re-tested every day on GitHub so its numbers reach
        last night. A winner made money after the reality check in every complete month and in its newest 15 days.
        The numbers below are measured over exactly the dates you pick, or the last N days you type — a trade counts
        when it opened and closed inside them. Nothing changes until you press Apply. Click an id to open its trades,
        with Export CSV.
      </p>
      {/* THE DAILY RE-TEST (operator, Oct 07, 2026: "it should be updated
          everyday justd like the backtest") — when the numbers were last
          brought up to date, and where today's re-test is */}
      {d?.retest && (
        <p className="mt-1 text-theme-xs text-gray-500 dark:text-gray-400">
          {d.retest.made_at
            ? `Last re-test: ${fmtWhen(d.retest.made_at)}, ${(d.retest.retested ?? 0).toLocaleString()} room strategies with prices up to ${d.retest.end_ms ? fmtWhenMs(d.retest.end_ms) : "—"}`
            : "Not re-tested yet — until the first daily re-test lands, the numbers are prompt 4's own"}
          {d.retest.unlisted > 0 && ` · ${d.retest.unlisted.toLocaleString()} kept since are re-tested from the next run`}
          {d.retest.why && ` · now: ${d.retest.why}`}
          {d.retest.error && <span className="text-error-500"> · last error: {d.retest.error}</span>}
        </p>
      )}
      <form className="mt-3 flex flex-wrap items-end gap-2 text-theme-xs text-gray-600 dark:text-gray-300"
        onSubmit={(e) => { e.preventDefault(); apply(); }}>
        <label className="flex flex-col gap-1">from<input type="date" className={`${sel} disabled:opacity-50`} value={draft.from} max={draft.to} disabled={byDays} onChange={(e) => set({ from: e.target.value })} /></label>
        <label className="flex flex-col gap-1">to<input type="date" className={`${sel} disabled:opacity-50`} value={draft.to} min={draft.from} disabled={byDays} onChange={(e) => set({ to: e.target.value })} /></label>
        <label className="flex flex-col gap-1">or last N days<input className={`${sel} w-24`} inputMode="decimal" placeholder="e.g. 3" value={draft.days} onChange={(e) => setDays(e.target.value)} /></label>
        <label className="flex flex-col gap-1">min win %<input className={`${sel} w-20`} inputMode="decimal" value={draft.minWin} onChange={(e) => set({ minWin: e.target.value })} /></label>
        <label className="flex flex-col gap-1">min profit $<input className={`${sel} w-20`} inputMode="decimal" value={draft.minProfit} onChange={(e) => set({ minProfit: e.target.value })} /></label>
        <label className="flex flex-col gap-1">find by id<input className={`${sel} w-28`} value={draft.find} placeholder="#ID" onChange={(e) => set({ find: e.target.value })} /></label>
        {/* Disabled from the press until the answer to what was applied
            lands (or the ask fails); a disabled default button also stops
            Enter. "clear" stays pressable. */}
        <button type="submit" disabled={waiting} aria-busy={waiting}
          className="inline-flex items-center gap-1.5 rounded-lg border border-brand-500 bg-brand-500 px-4 py-1 text-theme-xs font-semibold text-white hover:bg-brand-600 disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:bg-brand-500">
          {waiting && <span className="h-3 w-3 animate-spin rounded-full border-2 border-white/40 border-t-white" aria-hidden="true" />}
          {waiting ? "Loading…" : "Apply"}
        </button>
        <button type="button" className={btn} onClick={clear}>clear</button>
        {bad ? <span className="self-center text-error-500">{bad}</span>
          : waiting ? <span className="self-center text-gray-400">loading the room strategies…</span>
          : unsent ? <span className="self-center text-warning-600">changed — press Apply to use it</span> : null}
      </form>
      {err && <p className="mt-3 text-theme-xs text-error-500">could not read the room strategies — {err}</p>}
      {d && asked && (
        <>
          <p className="mt-3 text-theme-xs text-gray-500 dark:text-gray-400">
            {d.matched.toLocaleString()} of {d.kept.toLocaleString()} kept · {asked.days ? `last ${asked.days} day${asked.days === 1 ? "" : "s"}: ` : ""}{fmtWhen(d.from)} to {fmtWhen(d.to)}
            {words.length > 0 && ` · ${words.join(" · ")}`} · ${d.margin} a trade at {d.leverage}x
            {d.reality.took != null ? ` · reality check: practice takes ${(100 * d.reality.took).toFixed(0)}% of the backtest's trades, ${fmtMoney(-(d.reality.gap ?? 0))} a trade worse`
              : d.reality_pending ? " · the reality check is still being worked out (about a minute after a restart) — the column after it fills in then" : ""}
          </p>
          {d.kept > 0 && pastEnd && d.data_end != null && (
            <p className="mt-2 rounded-lg border border-warning-200 bg-warning-50 px-3 py-2 text-theme-xs text-warning-700 dark:border-warning-500/30 dark:bg-warning-500/10 dark:text-warning-400">
              {d.with_trades === 0
                ? `None of the ${d.kept.toLocaleString()} has a trade in these dates: their trades are measured up to ${fmtWhenMs(d.data_end)}. `
                : `${d.with_trades.toLocaleString()} of the ${d.kept.toLocaleString()} have a trade in these dates, and their trades are measured up to ${fmtWhenMs(d.data_end)}, so nothing after that is in these numbers. `}
              {d.retest?.made_at
                ? "The daily re-test measured them up to then; the next one brings them up to last night."
                : "Prompt 4 measured them up to then; the first daily re-test brings them up to last night."}
              {(asked.min_winrate > 0 || asked.min_profit != null) && " A row with no trade in these dates passes no win % or profit floor."}
            </p>
          )}
          {d.kept === 0 ? (
            <p className="mt-2 text-theme-xs text-gray-500 dark:text-gray-400">No winner kept yet — run prompt 4 and its winners land here.</p>
          ) : (
            <div className={`mt-2 overflow-x-auto transition-opacity ${waiting ? "opacity-50" : ""}`}>
              <table className="w-full min-w-[1200px] text-theme-xs">
                <thead><tr className="border-b border-gray-200 text-gray-500 dark:border-gray-700 dark:text-gray-400">
                  {cols.map((h) => <th key={h} className={th}>{h}</th>)}
                </tr></thead>
                <tbody className="divide-y divide-gray-100 text-gray-700 dark:divide-white/[0.05] dark:text-gray-300">
                  {d.rows.map((r) => (
                    <Fragment key={r.id}>
                      <tr className="cursor-pointer hover:bg-gray-50 dark:hover:bg-white/[0.03]" title="open its trades"
                        tabIndex={0} onClick={() => setOpen({ id: r.id, words: r.words })}
                        onKeyDown={(e) => { if (e.key === "Enter" && e.target === e.currentTarget) setOpen({ id: r.id, words: r.words }); }}>
                        <td className={td}>
                          <button type="button" title="open its trades" className="font-mono font-medium text-brand-600 underline-offset-2 hover:underline dark:text-brand-400"
                            onClick={(e) => { e.stopPropagation(); setOpen({ id: r.id, words: r.words }); }}>#{r.id}</button>
                        </td>
                        <td className="min-w-[280px] max-w-[360px] px-2 py-1.5 text-gray-700 dark:text-gray-300">{r.words}
                          {!r.still_works && <span className="ml-1 rounded bg-warning-50 px-1 text-[10px] text-warning-700 dark:bg-warning-500/10">stopped working</span>}</td>
                        <td className={td}>{r.found_by} · {fmtWhen(r.found_at)}</td>
                        <td className={td}>{r.trades.toLocaleString()}</td>
                        <td className={td}>{r.per_day}</td>
                        <td className={td}>{r.wins.toLocaleString()} / {r.losses.toLocaleString()}</td>
                        <td className={td}>{pct(r.winrate)}</td>
                        <td className={td}>{pct(r.break_even)}</td>
                        <td className={`${td} font-semibold ${tone(r.profit)}`}>{fmtMoney(r.profit)}</td>
                        <td className={`${td} ${tone(r.corrected)}`}>{fmtMoney(r.corrected)}</td>
                        <td className={`${td} ${tone(r.worst_day)}`}>{fmtMoney(r.worst_day)}</td>
                        <td className={td}>{r.worst_run_n ? `${fmtMoney(r.worst_run)} over ${r.worst_run_n}` : "—"}</td>
                        <td className={td}>{r.max_open}</td>
                        <td className={td}>${r.money_needed.toLocaleString()}</td>
                        <td className={`${td} ${tone(r.worst_month)}`}>{fmtMoney(r.worst_month)}</td>
                        <td className={td}>{r.deployable ? "yes" : <span title={r.deploy_why} className="text-gray-400">needs a new switch</span>}</td>
                      </tr>
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <PageButtons cur={d.page} pages={d.pages} goto={(n) => { setPage(n); setOpen(null); }} what="room strategies" />
          {/* A ROOM STRATEGY'S TRADES IN A POP-UP (operator, Oct 08, 2026: "when
              i click the id, i want it on pop up then i should have option to
              export via csv") — over the dates the table above answered */}
          <Modal isOpen={!!open} onClose={() => setOpen(null)} className="m-4 max-w-[960px] p-5 lg:p-6">
            {open && (
              <div role="dialog" aria-modal="true" aria-label={`Room strategy #${open.id}`}
                className="max-h-[80vh] overflow-y-auto pr-10 sm:pr-14">
                <StrategyTrades id={open.id} words={open.words} from_s={d.from} to_s={d.to} />
              </div>
            )}
          </Modal>
        </>
      )}
    </div>
  );
}

/** The most trades one CSV export reads (api.py TRADES_EXPORT_MAX). */
const EXPORT_MAX = 100_000;

/** One room strategy's trades that opened and closed in the dates its row was
 *  measured over — the same trades the row counts — oldest first, with the
 *  running total and the TOTAL PROFIT for the dates; ten a page, paged by the
 *  server. Export CSV writes every one of them, each date as the screen
 *  prints it (fmtWhenMs, this browser's clock). */
function StrategyTrades({ id, words, from_s, to_s }: { id: string; words: string; from_s: number; to_s: number }) {
  const [page, setPage] = useState(1);
  const [got, setGot] = useState<{ key: string; d: RoomStrategyTrades } | null>(null);
  const [err, setErr] = useState("");
  // "" idle, "busy" while the export reads, else what it has to say
  const [csv, setCsv] = useState("");
  const exportCsv = () => {
    setCsv("busy");
    api.roomStrategyTrades({ id, from_s, to_s, page: 1, per: EXPORT_MAX })
      .then((all) => {
        const q = (v: string | number) => `"${String(v).replace(/"/g, '""')}"`;
        const lines = [["#", "Opened", "Closed", "Held", "Profit", "Running total"].map(q).join(",")];
        for (const t of all.rows) {
          lines.push([t.n, fmtWhenMs(t.opened), fmtWhenMs(t.closed), heldFor(t.closed - t.opened),
            t.profit.toFixed(2), t.total.toFixed(2)].map(q).join(","));
        }
        lines.push([q("TOTAL PROFIT"), "", "", "", "", q(all.profit.toFixed(2))].join(","));
        // THE DATES' WIN RATE AS THE LAST ROW (operator, Oct 08, 2026: "when i
        // export the csv, show me the winrate for last row")
        lines.push([q("WIN RATE"), "", "", "", "",
          q(`${pct(all.winrate)} (${all.wins.toLocaleString()} won, ${all.losses.toLocaleString()} lost)`)].join(","));
        const url = URL.createObjectURL(new Blob(["\uFEFF" + lines.join("\r\n") + "\r\n"],
          { type: "text/csv;charset=utf-8" }));
        const a = document.createElement("a");
        a.href = url;
        a.download = `room-strategy-${id}-${dateBoxAt(from_s)}-to-${dateBoxAt(to_s)}.csv`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 2000);
        setCsv(all.rows.length < all.trades
          ? `exported the first ${all.rows.length.toLocaleString()} of ${all.trades.toLocaleString()} trades`
          : `exported ${all.trades.toLocaleString()} trade${all.trades === 1 ? "" : "s"}`);
      })
      .catch((e) => setCsv(`could not export — ${String(e?.message ?? e)}`));
  };
  const key = `${id}|${from_s}|${to_s}|${page}`;
  useEffect(() => {
    let live = true;
    api.roomStrategyTrades({ id, from_s, to_s, page })
      .then((x) => { if (live) { setGot({ key: `${id}|${from_s}|${to_s}|${page}`, d: x }); setErr(""); } })
      .catch((e) => { if (live) setErr(String(e?.message ?? e)); });
    return () => { live = false; };
  }, [id, from_s, to_s, page]);
  const th = "px-2 py-1 text-start font-medium whitespace-nowrap";
  const td = "px-2 py-1 whitespace-nowrap";
  if (err) return <p className="text-theme-xs text-error-500">could not read #{id}&apos;s trades — {err}</p>;
  if (!got) return <p className="text-theme-xs text-gray-400">reading #{id}&apos;s trades…</p>;
  const d = got.d;
  return (
    <div className={got.key === key ? "" : "opacity-60"}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-theme-sm font-semibold"><CopyId id={d.id} /></span>
        <button type="button" onClick={exportCsv} disabled={csv === "busy" || d.trades === 0}
          className="rounded-lg border border-brand-500 px-3 py-1 text-theme-xs font-medium text-brand-600 hover:bg-brand-50 disabled:cursor-not-allowed disabled:opacity-50 dark:text-brand-400 dark:hover:bg-brand-500/10">
          {csv === "busy" ? "Exporting…" : "Export CSV"}
        </button>
        {csv && csv !== "busy" && <span className="text-theme-xs text-gray-500 dark:text-gray-400">{csv}</span>}
      </div>
      <p className="mt-1 text-theme-xs text-gray-600 dark:text-gray-300">{words}</p>
      <p className="mt-2 text-theme-sm font-semibold text-gray-800 dark:text-white/90">
        TOTAL PROFIT <span className={tone(d.profit)}>{fmtMoney(d.profit)}</span>
        <span className="font-normal text-gray-500 dark:text-gray-400"> over {d.trades.toLocaleString()} trade{d.trades === 1 ? "" : "s"} ({d.wins.toLocaleString()} won, {d.losses.toLocaleString()} lost, win rate {pct(d.winrate)}) that opened and closed between {fmtWhen(d.from)} and {fmtWhen(d.to)} · ${d.margin} a trade at {d.leverage}x</span>
      </p>
      {d.trades === 0 ? (
        <p className="mt-1 text-theme-xs text-gray-500 dark:text-gray-400">
          No trade of #{d.id} opened and closed in these dates.{d.first != null && d.last != null
            ? ` Its ${d.saved.toLocaleString()} saved trades closed ${fmtWhenMs(d.first)} to ${fmtWhenMs(d.last)}.` : " It has no saved trades."}
        </p>
      ) : (
        <div className="mt-2 overflow-x-auto">
          <table className="w-auto text-theme-xs">
            <thead><tr className="border-b border-gray-200 text-gray-500 dark:border-gray-700 dark:text-gray-400">
              {["#", "Opened", "Closed", "Held", "Profit", "Running total"].map((h) => <th key={h} className={th}>{h}</th>)}
            </tr></thead>
            <tbody className="divide-y divide-gray-100 text-gray-700 dark:divide-white/[0.05] dark:text-gray-300">
              {d.rows.map((t) => (
                <tr key={t.n}>
                  <td className={td}>{t.n}</td>
                  <td className={td}>{fmtWhenMs(t.opened)}</td>
                  <td className={td}>{fmtWhenMs(t.closed)}</td>
                  <td className={td}>{heldFor(t.closed - t.opened)}</td>
                  <td className={`${td} ${tone(t.profit)}`}>{fmtMoney(t.profit)}</td>
                  <td className={`${td} ${tone(t.total)}`}>{fmtMoney(t.total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="mt-1 text-[10px] text-gray-400">The replay kept when each trade opened and closed and what it made — not which coin it was on.</p>
      <PageButtons cur={d.page} pages={d.pages} goto={setPage} what="room strategy trades" />
    </div>
  );
}

/** A rule set's id with a copy button (#ID, the id alone on the clipboard). */
function CopyId({ id }: { id: string }) {
  const [ok, setOk] = useState(false);
  return (
    <button type="button" title="copy the id" className="font-mono text-gray-800 hover:text-brand-600 dark:text-white/90"
      onClick={() => { navigator.clipboard?.writeText(id).then(() => { setOk(true); setTimeout(() => setOk(false), 1200); }).catch(() => {}); }}>
      #{id}{ok ? " ✓" : ""}
    </button>
  );
}
