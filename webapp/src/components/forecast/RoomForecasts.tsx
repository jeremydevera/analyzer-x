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
import { useCallback, useState } from "react";
import { api, fmtMoney, fmtWhen, Forecast, Forecasts, ForecastsLive, RoomNow } from "@/lib/api";
import { useLiveRefresh } from "@/lib/live";

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

function Group({ label, g }: { label: string; g: RoomNow["hours"]["market"] }) {
  return (
    <tr>
      <td className="py-1 pr-2 text-gray-600 dark:text-gray-300">{label}</td>
      <td className="py-1 pr-2 text-gray-600 dark:text-gray-300">{g.trades.toLocaleString()}</td>
      <td className="py-1 pr-2 text-gray-600 dark:text-gray-300">{g.trades ? `${g.wins} / ${g.losses}` : "—"}</td>
      <td className="py-1 pr-2 text-gray-600 dark:text-gray-300">{pct(g.winrate)}</td>
      <td className={`py-1 pr-2 font-medium ${tone(g.trades ? g.profit : null)}`}>{g.trades ? fmtMoney(g.profit) : "—"}</td>
      <td className={`py-1 ${tone(g.per_trade)}`}>{fmtMoney(g.per_trade)}</td>
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
          <dd className={tone(r.worst_case.up_to)}>{r.worst_case.open ? `up to ${fmtMoney(r.worst_case.up_to)} if all ${r.worst_case.open.toLocaleString()} open trades hit their stop now` : "no open trade"}</dd></div>
        <div><dt className="text-gray-400">costs</dt>
          <dd className="text-gray-700 dark:text-gray-300">
            {r.costs.matched ? <>{fmtMoney(-r.costs.total)} in total, {fmtMoney(r.costs.per_trade == null ? null : -r.costs.per_trade)} a trade · <span className={tone(r.costs.without_costs)}>{fmtMoney(r.costs.without_costs)} without costs</span>
              {r.costs.matched < r.costs.of && <span className="text-gray-400"> ({r.costs.matched} of {r.costs.of} trades matched to their opening)</span>}</> : "no closed trade yet"}
          </dd></div>
        <div><dt className="text-gray-400">September research</dt>
          <dd className="text-gray-700 dark:text-gray-300">{res
            ? <>{fmtMoney(res.profit)} · {fmtMoney(resPer)} a trade · {res.winrate}% wins · most open {res.max_open.toLocaleString()}</>
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
            <p className="text-theme-xs font-medium text-gray-700 dark:text-gray-300">Stock coins: market hours vs nights and weekends</p>
            <p className="text-[10px] text-gray-400">stock coin = {r.hours.rule}; split by {r.hours.split_by}; market hours = 9:30am–4pm New York, Monday–Friday · {r.hours.stock_trades.toLocaleString()} stock trades, {r.hours.other_trades.toLocaleString()} other trades not counted here</p>
            <div className="overflow-x-auto">
              <table className="mt-1 w-full min-w-[420px] text-theme-xs">
                <thead><tr className="text-start text-gray-400">
                  {["when it opened", "trades", "won / lost", "win rate", "profit", "a trade"].map((h) => <th key={h} className="py-1 pr-2 text-start font-medium">{h}</th>)}
                </tr></thead>
                <tbody>
                  <Group label="market hours" g={r.hours.market} />
                  <Group label="nights and weekends" g={r.hours.off} />
                </tbody>
              </table>
            </div>
          </div>
          <div>
            <p className="text-theme-xs font-medium text-gray-700 dark:text-gray-300">The coins losing the most</p>
            {r.losers.length ? (
              <div className="overflow-x-auto">
                <table className="mt-1 w-full min-w-[360px] text-theme-xs">
                  <thead><tr className="text-start text-gray-400">
                    {["coin", "trades", "won / lost", "profit"].map((h) => <th key={h} className="py-1 pr-2 text-start font-medium">{h}</th>)}
                  </tr></thead>
                  <tbody>
                    {r.losers.map((l) => (
                      <tr key={l.coin}>
                        <td className="py-1 pr-2 font-medium text-gray-700 dark:text-gray-300">{l.coin}</td>
                        <td className="py-1 pr-2 text-gray-600 dark:text-gray-300">{l.trades}</td>
                        <td className="py-1 pr-2 text-gray-600 dark:text-gray-300">{l.wins} / {l.losses}</td>
                        <td className="py-1 text-error-500">{fmtMoney(l.profit)}</td>
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
    <div className="mt-2 overflow-x-auto">
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

function History({ d, page, setPage }: { d: Forecasts; page: number; setPage: (n: number) => void }) {
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
                {["made", "verdict", "why", "the pick since then", ""].map((h, i) => (
                  <th key={i} className="px-2 py-1.5 text-start font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
              {d.forecasts.map((f, i) => (
                <tr key={`${f.at}-${i}`} className="align-top">
                  <td className="px-2 py-1.5 text-gray-600 dark:text-gray-300">
                    {fmtWhen(f.at)}
                    <span className="block text-[10px] text-gray-400">{SOURCE[f.source ?? "prompt"] ?? f.source}</span>
                  </td>
                  <td className="px-2 py-1.5"><Badge kind={f.verdict === "pick" ? "good" : "info"}>{VERDICT[f.verdict]}{f.pick ? `: ${roomName(f.pick)}` : ""}</Badge></td>
                  <td className="px-2 py-1.5 text-gray-600 dark:text-gray-300">
                    {f.pick_why}
                    {open === i && <ForecastDetail f={f} />}
                  </td>
                  <td className="px-2 py-1.5"><SinceCell f={f} /></td>
                  <td className="px-2 py-1.5">
                    <button type="button" onClick={() => setOpen(open === i ? null : i)} aria-expanded={open === i} className={btn}>
                      {open === i ? "hide" : "rooms then"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {d.pages > 1 && (
        <div className="mt-3 flex items-center gap-2 text-theme-xs text-gray-600 dark:text-gray-300">
          <button type="button" disabled={page <= 1} onClick={() => { setPage(page - 1); setOpen(null); }} className={`${btn} disabled:opacity-40`}>newer</button>
          <span>page {d.page} of {d.pages}</span>
          <button type="button" disabled={page >= d.pages} onClick={() => { setPage(page + 1); setOpen(null); }} className={`${btn} disabled:opacity-40`}>older</button>
        </div>
      )}
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
          </div>
        )}
      </div>

      {live && (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          {live.rooms.map((r) => <RoomCard key={r.id} r={r} rules={live.rules} />)}
        </div>
      )}

      {err && <p className="text-theme-xs text-error-500">could not read the saved forecasts — {err}</p>}
      {d && <History d={d} page={page} setPage={setPage} />}

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
