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
import { Fragment, useCallback, useState } from "react";
import { api, dateBoxValue, fmtMoney, fmtWhen, Forecast, Forecasts, ForecastsLive, RoomBacktest, RoomGroup, RoomNow, RoomStrategies } from "@/lib/api";
import { useLiveRefresh } from "@/lib/live";
import PageButtons from "@/components/common/PageButtons";

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
        <tbody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
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
            <tbody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
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
          <tbody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
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

/** BACKTEST A ROOM (operator, Oct 02, 2026: "i want ability to backtest room
 *  in forecast v1, i want option to filter date range to backtest so i can see
 *  if the deployed tabs attached matches the backtest"). For the strategies
 *  switched on in the room now, their backtest trades beside their practice
 *  trades over the chosen days — the same window for both, from each
 *  strategy's switch-on to the backtest's last candle. Sorted and paged by the
 *  server (tradingagents/room_backtest.py). */
function RoomBacktestPanel({ rooms }: { rooms: RoomNow[] }) {
  const live = rooms.filter((r) => !r.retired);
  const [room, setRoom] = useState(live[0]?.id ?? "main");
  const [from, setFrom] = useState(dateBoxValue(7));
  const [to, setTo] = useState(dateBoxValue(0));
  const [sort, setSort] = useState("gap");
  const [d, setD] = useState<RoomBacktest | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const run = (pg = 1, so = sort) => {
    setBusy(true); setErr("");
    api.roomBacktest({ room, from_s: dayStart(from), to_s: dayStart(to) + 86_399, sort: so, page: pg })
      .then((x) => setD(x))
      .catch((e) => setErr(String(e?.message ?? e)))
      .finally(() => setBusy(false));
  };
  const name = (id: string) => rooms.find((r) => r.id === id)?.name ?? id;
  const sel = "rounded-lg border border-gray-300 bg-transparent px-2 py-1 text-theme-xs dark:border-gray-700 dark:text-gray-300";
  const th = "px-2 py-1.5 text-start font-medium whitespace-nowrap";
  const td = "px-2 py-1.5 whitespace-nowrap";
  const m = d?.match;
  const compared = m ? m.same + m.different : 0;
  const side = (label: string, s: RoomBacktest["backtest"]) => (
    <tr>
      <td className={`${td} font-medium text-gray-700 dark:text-gray-300`}>{label}</td>
      <td className={`${td} font-semibold ${tone(s.trades ? s.profit : null)}`}>{s.trades ? fmtMoney(s.profit) : "—"}</td>
      <td className={td}>{s.trades.toLocaleString()}</td>
      <td className={td}>{s.wins.toLocaleString()} / {s.losses.toLocaleString()}</td>
      <td className={td}>{pct(s.winrate)}</td>
      <td className={td}>{s.worst_run_trades ? `${fmtMoney(s.worst_run)} over ${s.worst_run_trades}` : "—"}</td>
    </tr>
  );
  return (
    <div className={card}>
      <h3 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">Backtest a room</h3>
      <p className="mt-1 text-theme-xs text-gray-500 dark:text-gray-400">
        For every strategy switched on in the room now: what its backtest says, beside what the practice account
        really did, over the days you pick. Each strategy is counted from the moment it was switched on, and both
        sides stop at the backtest&apos;s last candle (the last daily update).
      </p>
      <div className="mt-3 flex flex-wrap items-end gap-2 text-theme-xs text-gray-600 dark:text-gray-300">
        <label className="flex flex-col gap-1">room
          <select className={sel} value={room} onChange={(e) => setRoom(e.target.value)}>
            {live.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1">from
          <input type="date" className={sel} value={from} max={to} onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1">to
          <input type="date" className={sel} value={to} min={from} onChange={(e) => setTo(e.target.value)} />
        </label>
        <button type="button" disabled={busy || !from || !to} onClick={() => run(1)}
          className="rounded-lg bg-brand-500 px-4 py-1.5 font-medium text-white hover:bg-brand-600 disabled:opacity-50">
          {busy ? "backtesting…" : "Backtest"}
        </button>
      </div>
      {err && <p className="mt-3 text-theme-xs text-error-500">could not backtest the room — {err}</p>}
      {d && m && (
        <>
          <p className="mt-3 text-theme-xs text-gray-500 dark:text-gray-400">
            {name(d.room)} · {fmtWhen(d.from)} to {fmtWhen(d.to)} · {d.slots.toLocaleString()} strategies switched on,
            {" "}{d.traded.toLocaleString()} with a trade in the range · ${d.margin} a trade at {d.leverage}x
            {d.backtest_end_ms ? ` · backtest up to ${fmtWhen(d.backtest_end_ms / 1000)}` : ""}
            {d.no_backtest ? ` · ${d.no_backtest.toLocaleString()} strategies have no backtest yet` : ""}
          </p>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full min-w-[560px] text-theme-xs">
              <thead><tr className="border-b border-gray-200 text-gray-500 dark:border-gray-700 dark:text-gray-400">
                {["", "Profit", "Trades", "Won / lost", "Win rate", "Worst losing run"].map((h) => <th key={h} className={th}>{h}</th>)}
              </tr></thead>
              <tbody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
                {side("Backtest", d.backtest)}
                {side("Practice", d.practice)}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-theme-xs text-gray-700 dark:text-gray-300">
            <b>Trades both took:</b> {compared.toLocaleString()} — {m.same.toLocaleString()} ended the same way,{" "}
            <span className={m.different ? "text-error-500" : ""}>{m.different.toLocaleString()} ended differently</span>
            {compared ? ` (${(100 * m.same / compared).toFixed(1)}% agree)` : ""}
            {" · "}practice only: {m.practice_only.toLocaleString()}
            {m.after_backtest ? ` · ${m.after_backtest.toLocaleString()} practice trades closed after the backtest's last candle (checked after the next daily update)` : ""}
          </p>
          {m.backtest_only > 0 && (
            <div className="mt-2 text-theme-xs text-gray-600 dark:text-gray-300">
              <b>Backtest trades the practice account did not take: {m.backtest_only.toLocaleString()}</b>
              <ul className="mt-1 list-disc pl-5">
                {Object.entries(d.reasons).filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1]).map(([k, n]) => (
                  <li key={k}>{n.toLocaleString()} — {d.reason_labels[k] ?? k}</li>
                ))}
              </ul>
            </div>
          )}
          <div className="mt-4 flex flex-wrap items-center gap-2 text-theme-xs text-gray-500 dark:text-gray-400">
            <span>sort by</span>
            <select className={sel} value={sort} onChange={(e) => { setSort(e.target.value); run(1, e.target.value); }}>
              <option value="gap">biggest profit gap</option>
              <option value="practice">most practice trades</option>
              <option value="backtest">most backtest trades</option>
              <option value="different">most different results</option>
            </select>
            <span className="ml-auto">{d.traded.toLocaleString()} strategies with a trade in the range</span>
          </div>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full min-w-[900px] text-theme-xs">
              <thead><tr className="border-b border-gray-200 text-gray-500 dark:border-gray-700 dark:text-gray-400">
                {["Strategy", "TP", "SL", "Lev", "Backtest", "Practice", "Same / different", "Backtest only", "Profit gap"].map((h) => <th key={h} className={th}>{h}</th>)}
              </tr></thead>
              <tbody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
                {d.rows.map((r) => (
                  <tr key={r.slot}>
                    <td className={td}>
                      {r.id ? <span className="font-mono text-gray-800 dark:text-white/90">#{r.id} </span> : null}
                      <span className="text-gray-700 dark:text-gray-300">{r.coin}</span>
                      <span className="block text-[10px] text-gray-400">{r.key}{r.on_at ? ` · on since ${fmtWhen(r.on_at)}` : ""}</span>
                    </td>
                    <td className={td}>{r.tp == null ? "—" : `${r.tp}%`}</td>
                    <td className={td}>{r.sl == null ? "—" : `${r.sl}%`}</td>
                    <td className={td}>{d.leverage}x</td>
                    <td className={td}>{r.backtest.trades} · {r.backtest.wins}W/{r.backtest.losses}L · <span className={tone(r.backtest.profit)}>{fmtMoney(r.backtest.profit)}</span></td>
                    <td className={td}>{r.practice.trades} · {r.practice.wins}W/{r.practice.losses}L · <span className={tone(r.practice.profit)}>{fmtMoney(r.practice.profit)}</span></td>
                    <td className={td}>{r.same} / <span className={r.different ? "text-error-500" : ""}>{r.different}</span></td>
                    <td className={td}>{r.backtest_only}</td>
                    <td className={`${td} ${tone(r.gap)}`}>{fmtMoney(r.gap)}</td>
                  </tr>
                ))}
                {d.rows.length === 0 && (
                  <tr><td colSpan={9} className="py-3 text-gray-500">
                    No trade in this range for the {d.slots.toLocaleString()} strategies switched on in {name(d.room)}
                    {d.backtest_end_ms ? ` (the backtest stops at ${fmtWhen(d.backtest_end_ms / 1000)})` : ""}.
                  </td></tr>
                )}
              </tbody>
            </table>
          </div>
          {/* each page is measured afresh, so the buttons wait while it is */}
          <PageButtons cur={d.page} pages={d.pages} goto={(n) => run(n)} busy={busy} what="room backtest" />
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
export function RoomsAndBacktest() {
  const [live, setLive] = useState<ForecastsLive | null>(null);
  const [saved, setSaved] = useState<Forecasts | null>(null);
  const [err, setErr] = useState("");
  const load = useCallback(() => api.forecastsLive()
    .then((d) => { setLive(d); setErr(""); })
    .catch((e) => setErr(String(e?.message ?? e))), []);
  useLiveRefresh(load, 15_000);
  // THE PROMPTS WITH THEIR COPY BUTTONS — prompt 4, "Find new winning room
  // strategies", is one of the two things the operator said matter here
  const loadPrompts = useCallback(() => api.forecasts(1).then(setSaved).catch(() => {}), []);
  useLiveRefresh(loadPrompts, 300_000);
  return (
    <>
      <RoomStrategiesTable />
      {saved && saved.prompts.length > 0 && (
        <div className={card}>
          <h3 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">Prompts</h3>
          <p className="mt-1 text-theme-xs text-gray-500 dark:text-gray-400">
            Copy one and paste it to Claude. Prompt 4 finds new winning room strategies and keeps them in Best room rules above.
          </p>
          <div className="mt-3 grid items-start gap-3 lg:grid-cols-2">
            {saved.prompts.map((p) => <PromptBox key={p.title} title={p.title} text={p.text} />)}
          </div>
        </div>
      )}
      {err && !live && <p className="text-theme-xs text-error-500">could not read the rooms — {err}</p>}
      {!live && !err && <p className="text-theme-xs text-gray-400">reading every room&apos;s trade record…</p>}
      {live && <RoomBacktestPanel rooms={live.rooms} />}
      {live && <RoomTable rooms={live.rooms} rules={live.rules} />}
    </>
  );
}

/** ROOM STRATEGIES — every winner prompt 4 kept (operator, Oct 02, 2026: "when
 *  i run that prompt i want you to look for all kinds of combination then add
 *  it in room strategy"). Re-measured on the server over exactly the dates
 *  chosen, from each winner's own stored trades; filtered, sorted and paged
 *  there (tradingagents/room_strategies.table). Never deleted: a winner whose
 *  newest 15 days lost says "stopped working". */
function RoomStrategiesTable() {
  const [from, setFrom] = useState(dateBoxValue(30));
  const [to, setTo] = useState(dateBoxValue(0));
  const [minWin, setMinWin] = useState("");
  const [minProfit, setMinProfit] = useState("");
  const [win, setWin] = useState("");
  const [dep, setDep] = useState("");
  const [find, setFind] = useState("");
  const [sort, setSort] = useState("worst_month");
  const [page, setPage] = useState(1);
  const [d, setD] = useState<RoomStrategies | null>(null);
  const [err, setErr] = useState("");
  const load = useCallback(() => {
    if (!from || !to) return;
    api.roomStrategies({ from_s: dayStart(from), to_s: dayStart(to) + 86_399,
      min_winrate: Number(minWin) || 0, min_profit: minProfit === "" ? null : Number(minProfit),
      window: Number(win) || 0, deployable: dep, find, sort, page })
      .then((x) => { setD(x); setErr(""); })
      .catch((e) => setErr(String(e?.message ?? e)));
  }, [from, to, minWin, minProfit, win, dep, find, sort, page]);
  useLiveRefresh(load, 60_000, [load]);
  const sel = "rounded-lg border border-gray-300 bg-transparent px-2 py-1 text-theme-xs dark:border-gray-700 dark:text-gray-300";
  const th = "px-2 py-1.5 text-start font-medium whitespace-nowrap";
  const td = "px-2 py-1.5 whitespace-nowrap";
  const reset = () => setPage(1);
  const quick = (back: number) => { setFrom(dateBoxValue(back)); setTo(dateBoxValue(0)); reset(); };
  return (
    <div className={card}>
      <h3 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">Room strategies</h3>
      <p className="mt-1 text-theme-xs text-gray-500 dark:text-gray-400">
        Every winner prompt 4 found and kept, never deleted. A winner made money after the reality check in every
        complete month and in its newest 15 days. The numbers below are measured over exactly the dates you pick.
      </p>
      <div className="mt-3 flex flex-wrap items-end gap-2 text-theme-xs text-gray-600 dark:text-gray-300">
        <label className="flex flex-col gap-1">from<input type="date" className={sel} value={from} max={to} onChange={(e) => { setFrom(e.target.value); reset(); }} /></label>
        <label className="flex flex-col gap-1">to<input type="date" className={sel} value={to} min={from} onChange={(e) => { setTo(e.target.value); reset(); }} /></label>
        <button type="button" className={btn} onClick={() => quick(15)}>last 15 days</button>
        <button type="button" className={btn} onClick={() => quick(30)}>last 30 days</button>
        <label className="flex flex-col gap-1">min win %<input className={`${sel} w-20`} inputMode="decimal" value={minWin} onChange={(e) => { setMinWin(e.target.value); reset(); }} /></label>
        <label className="flex flex-col gap-1">min profit $<input className={`${sel} w-20`} inputMode="decimal" value={minProfit} onChange={(e) => { setMinProfit(e.target.value); reset(); }} /></label>
        <label className="flex flex-col gap-1">judged on
          <select className={sel} value={win} onChange={(e) => { setWin(e.target.value); reset(); }}>
            <option value="">any days</option><option value="7">7 days</option><option value="15">15 days</option><option value="30">30 days</option>
          </select></label>
        <label className="flex flex-col gap-1">a room can run it
          <select className={sel} value={dep} onChange={(e) => { setDep(e.target.value); reset(); }}>
            <option value="">all</option><option value="yes">yes</option><option value="no">needs a new switch</option>
          </select></label>
        <label className="flex flex-col gap-1">sort
          <select className={sel} value={sort} onChange={(e) => { setSort(e.target.value); reset(); }}>
            <option value="worst_month">worst month (best first)</option><option value="corrected">profit after reality check</option>
            <option value="profit">profit</option><option value="winrate">win rate</option><option value="found">newest found</option>
          </select></label>
        <label className="flex flex-col gap-1">find by id<input className={`${sel} w-28`} value={find} placeholder="#ID" onChange={(e) => { setFind(e.target.value); reset(); }} /></label>
      </div>
      {err && <p className="mt-3 text-theme-xs text-error-500">could not read the room strategies — {err}</p>}
      {d && (
        <>
          <p className="mt-3 text-theme-xs text-gray-500 dark:text-gray-400">
            {d.matched.toLocaleString()} of {d.kept.toLocaleString()} kept · {fmtWhen(d.from)} to {fmtWhen(d.to)} · ${d.margin} a trade at {d.leverage}x
            {d.reality.took != null ? ` · reality check: practice takes ${(100 * d.reality.took).toFixed(0)}% of the backtest's trades, ${fmtMoney(-(d.reality.gap ?? 0))} a trade worse` : ""}
          </p>
          {d.kept === 0 ? (
            <p className="mt-2 text-theme-xs text-gray-500 dark:text-gray-400">No winner kept yet — run prompt 4 and its winners land here.</p>
          ) : (
            <div className="mt-2 overflow-x-auto">
              <table className="w-full min-w-[1200px] text-theme-xs">
                <thead><tr className="border-b border-gray-200 text-gray-500 dark:border-gray-700 dark:text-gray-400">
                  {["ID", "Rules", "Found", "Trades", "A day", "Won / lost", "Win rate", "Break-even", "Profit",
                    "After reality check", "Worst day", "Worst losing run", "Most open", "Money needed", "Worst month", "Room can run it"].map((h) => <th key={h} className={th}>{h}</th>)}
                </tr></thead>
                <tbody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
                  {d.rows.map((r) => (
                    <tr key={r.id}>
                      <td className={td}><CopyId id={r.id} /></td>
                      <td className="max-w-[320px] px-2 py-1.5 text-gray-700 dark:text-gray-300">{r.words}
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
                      <td className={td}>{fmtMoney(r.money_needed)}</td>
                      <td className={`${td} ${tone(r.worst_month)}`}>{fmtMoney(r.worst_month)}</td>
                      <td className={td}>{r.deployable ? "yes" : <span title={r.deploy_why} className="text-gray-400">needs a new switch</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <PageButtons cur={d.page} pages={d.pages} goto={setPage} what="room strategies" />
        </>
      )}
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
