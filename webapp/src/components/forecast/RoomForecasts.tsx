"use client";
/** AUTO TRADE -> FORECAST — the saved forecasts of which trading room is best.
 *
 * Operator, Oct 01, 2026: *"create a forecast tab, then if i run this prompt
 * make sure it will generate a new forecast / take note create forecast tab
 * only for now"*. A forecast is MADE by a Claude session running the prompt
 * below (docs/FORECAST-PROMPTS.md) and saved with
 * `python -m tradingagents.room_forecasts add`; this screen only shows what
 * was saved — it works nothing out, so it can never disagree with the
 * forecast it is showing. Newest first, ten a page, paged by the server.
 */
import { useCallback, useState } from "react";
import { api, fmtMoney, fmtWhen, Forecast, Forecasts } from "@/lib/api";
import { useLiveRefresh } from "@/lib/live";

const roomName = (id: string) => (id === "main" ? "Main" : `#${id}`);

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
        <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
          className="rounded-lg border border-gray-300 px-3 py-1 text-theme-xs text-gray-600 dark:border-gray-700 dark:text-gray-300">
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

function ForecastCard({ f, latest }: { f: Forecast; latest: boolean }) {
  const rooms = [...f.rooms].sort((a, b) => (b.real.per_trade ?? 0) - (a.real.per_trade ?? 0));
  return (
    <div className={`rounded-2xl border bg-white p-5 dark:bg-white/[0.03] ${latest ? "border-brand-500" : "border-gray-200 dark:border-white/[0.05]"}`}>
      <p className="flex flex-wrap items-center gap-2 text-theme-sm font-semibold text-gray-800 dark:text-white/90">
        {latest ? "Latest forecast" : "Forecast"} · {fmtWhen(f.at)}
        <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${f.verdict === "pick"
          ? "bg-success-50 text-success-600 dark:bg-success-500/15"
          : "bg-gray-100 text-gray-600 dark:bg-white/[0.06] dark:text-gray-300"}`}>
          {VERDICT[f.verdict]}{f.pick ? `: ${roomName(f.pick)}` : ""}
        </span>
        {f.artifact && (
          <a href={f.artifact} target="_blank" rel="noreferrer"
            className="text-theme-xs font-normal text-brand-500 hover:underline">full table ↗</a>
        )}
      </p>
      <p className="mt-1 text-theme-xs text-gray-600 dark:text-gray-300">{f.pick_why}</p>
      {f.note && <p className="mt-1 text-[11px] text-gray-400">{f.note}</p>}
      <p className="mt-2 text-[11px] text-gray-400">practice money · $5 per trade at 20x ($100 of coin) · ranked by real profit per trade</p>
      <div className="mt-1 overflow-x-auto">
        <table className="w-full min-w-[760px] text-theme-xs">
          <thead>
            <tr className="text-start text-gray-500 dark:text-gray-400">
              {["room", "real profit", "won / lost", "win rate", "break-even", "per trade",
                "worst losing run", "open", "days", "research profit"].map((h) => (
                <th key={h} className="px-2 py-1.5 text-start font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
            {rooms.map((r) => {
              const above = r.real.winrate >= r.real.breakeven;
              return (
                <tr key={r.id} className={f.pick === r.id ? "bg-success-50/60 dark:bg-success-500/10" : ""}>
                  <td className="px-2 py-1.5">
                    <span className="font-semibold text-gray-800 dark:text-white/90">{roomName(r.id)}</span>
                    {r.retired && <span className="ml-1 text-[10px] text-gray-400">(retired)</span>}
                    {r.rules && <span className="block text-[10px] text-gray-400">{r.rules}</span>}
                  </td>
                  <td className={`px-2 py-1.5 font-semibold ${r.real.profit >= 0 ? "text-success-600" : "text-error-500"}`}>{fmtMoney(r.real.profit)}</td>
                  <td className="px-2 py-1.5 text-gray-600 dark:text-gray-300">
                    <span className="text-success-600">{r.real.wins.toLocaleString()}</span> / <span className="text-error-500">{r.real.losses.toLocaleString()}</span>
                    <span className="block text-[10px] text-gray-400">{r.real.closed.toLocaleString()} closed</span>
                  </td>
                  <td className={`px-2 py-1.5 ${above ? "text-success-600" : "text-error-500"}`}>{r.real.winrate.toFixed(1)}%</td>
                  <td className="px-2 py-1.5 text-gray-500 dark:text-gray-400">{r.real.breakeven.toFixed(1)}%</td>
                  <td className={`px-2 py-1.5 ${r.real.per_trade >= 0 ? "text-success-600" : "text-error-500"}`}>{fmtMoney(r.real.per_trade)}</td>
                  <td className="px-2 py-1.5 text-error-500">{fmtMoney(r.real.worst_run)} <span className="text-[10px] text-gray-400">over {r.real.worst_run_trades}</span></td>
                  <td className="px-2 py-1.5 text-gray-600 dark:text-gray-300">{r.real.open.toLocaleString()}</td>
                  <td className="px-2 py-1.5 text-gray-600 dark:text-gray-300">{r.real.days.toFixed(1)}</td>
                  <td className="px-2 py-1.5 text-gray-500 dark:text-gray-400">{r.research?.profit != null ? fmtMoney(r.research.profit) : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function RoomForecasts() {
  const [d, setD] = useState<Forecasts | null>(null);
  const [err, setErr] = useState("");
  const [page, setPage] = useState(1);
  const load = useCallback(() => {
    api.forecasts(page).then((r) => { setD(r); setErr(""); })
      .catch((e) => setErr(String(e?.message ?? e)));
  }, [page]);
  useLiveRefresh(load, 30_000, [load]);

  return (
    <div className="flex flex-col gap-5">
      <div className="overflow-hidden rounded-2xl border border-gray-200 bg-white p-5 dark:border-white/[0.05] dark:bg-white/[0.03]">
        <h3 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">Room forecasts</h3>
        <p className="mt-1 text-theme-xs text-gray-500 dark:text-gray-400">
          Which trading room looks best, from its real practice results and its research. Each
          forecast is made when you paste prompt 1 into Claude and is kept here, newest first;
          prompt 2 checks every saved forecast against what happened since.
        </p>
        {err && <p className="mt-3 text-theme-xs text-error-500">could not read the forecasts — {err}</p>}
        {!d && !err && <p className="mt-3 text-theme-xs text-gray-400">reading the saved forecasts…</p>}
        {d && (
          <>
            <div className="mt-4 grid gap-3 lg:grid-cols-2">
              {d.prompts.map((p) => <PromptBox key={p.title} title={p.title} text={p.text} />)}
            </div>
            <p className="mt-4 text-theme-xs text-gray-500 dark:text-gray-400">
              {d.total
                ? `${d.total.toLocaleString()} forecast${d.total === 1 ? "" : "s"} saved · page ${d.page} of ${d.pages}`
                : "No forecast saved yet — copy prompt 1 into Claude; the forecast it makes appears here."}
              {d.unreadable ? ` · ${d.unreadable.toLocaleString()} saved line(s) could not be read` : ""}
            </p>
          </>
        )}
      </div>
      {d?.forecasts.map((f, i) => (
        <ForecastCard key={`${f.at}-${i}`} f={f} latest={d.page === 1 && i === 0} />
      ))}
      {d && d.pages > 1 && (
        <div className="flex items-center gap-2 text-theme-xs text-gray-600 dark:text-gray-300">
          <button type="button" disabled={page <= 1} onClick={() => setPage(page - 1)}
            className="rounded-lg border border-gray-300 px-3 py-1 disabled:opacity-40 dark:border-gray-700">newer</button>
          <span>page {d.page} of {d.pages}</span>
          <button type="button" disabled={page >= d.pages} onClick={() => setPage(page + 1)}
            className="rounded-lg border border-gray-300 px-3 py-1 disabled:opacity-40 dark:border-gray-700">older</button>
        </div>
      )}
    </div>
  );
}
