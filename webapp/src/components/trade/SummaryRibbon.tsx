"use client";
/** The system ribbon: process, wallet, today, all-time — polled every 10s
 * from /api/trade/summary, the same numbers the runner acts on. */
import { useEffect, useState } from "react";
import { fmtMoney, tradeApi, TradeSummary } from "@/lib/api";
import Badge from "@/components/ui/badge/Badge";
import Button from "@/components/ui/button/Button";

const money = (v: number | null | undefined, dash = "—") =>
  v == null ? dash : `${v >= 0 ? "+" : ""}${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

function Tile({ label, value, sub, tone }: { label: string; value: string; sub: string; tone?: "up" | "down" | "flat" }) {
  const color = tone === "up" ? "text-success-600" : tone === "down" ? "text-error-500" : "text-gray-800 dark:text-white/90";
  return (
    <div className="rounded-2xl border border-gray-200 bg-white p-4 dark:border-white/[0.05] dark:bg-white/[0.03]">
      <p className="text-theme-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">{label}</p>
      <p className={`mt-1 text-xl font-semibold ${color}`}>{value}</p>
      <p className="mt-0.5 text-theme-xs text-gray-500 dark:text-gray-400">{sub}</p>
    </div>
  );
}

export default function SummaryRibbon({ onChanged }: { onChanged?: () => void }) {
  const [s, setS] = useState<TradeSummary | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [armed, setArmed] = useState(false);
  const [note, setNote] = useState("");
  const [sup, setSup] = useState<Awaited<ReturnType<typeof tradeApi.supervisor>> | null>(null);

  const load = () =>
    tradeApi.summary().then((d) => { setS(d); setErr(""); }).catch((e) => setErr(String(e)));

  const loadSup = () => tradeApi.supervisor().then(setSup).catch(() => {});

  useEffect(() => {
    load();
    loadSup();
    const t = setInterval(load, 10000);
    const su = setInterval(loadSup, 15000);
    return () => { clearInterval(t); clearInterval(su); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const halt = async () => {
    const on = !s?.halted;
    if (on && !confirm("Halt entries?\n\nNo NEW trade will be opened. Open positions keep their exchange-side stops and can still close on their own.")) return;
    setBusy(true);
    try { await tradeApi.halt(on); await load(); onChanged?.(); }
    catch (e) { setErr(String(e)); } finally { setBusy(false); }
  };

  const panic = async () => {
    const n = (s?.open_positions.length ?? 0);
    const worth = s?.open_unrealized ?? 0;
    if (!confirm(`PANIC — close everything at market?\n\nThis halts entries, stops the runner, and closes ${n} real position${n === 1 ? "" : "s"} NOW. Unrealized ${money(worth)} USDT becomes real.\n\nThere is no undo.`)) return;
    setBusy(true);
    try {
      const got = await tradeApi.panic(true);
      setNote(`PANIC done — halted, runner ${got.runner_stopped ? "stopped" : "was not running"}, closed ${got.closed.length}${got.failed.length ? `, FAILED on ${got.failed.join(", ")}` : ""}.`);
      setArmed(false);
      await load();
      onChanged?.();
    } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  };

  const runner = async (action: "start" | "stop") => {
    if (action === "stop" && !confirm("Stop the runner? Open positions keep their exchange-side brackets, but no new trades will be taken.")) return;
    setBusy(true);
    try {
      if (action === "start") await tradeApi.runnerStart();
      else await tradeApi.runnerStop();
      await load();
      onChanged?.();
    } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  };

  if (err) return <div className="rounded-2xl border border-error-300 bg-error-50 p-4 text-sm text-error-600 dark:border-error-500/30 dark:bg-error-500/10">Trade summary unreachable: {err}</div>;
  if (!s) return <div className="rounded-2xl border border-gray-200 bg-white p-4 text-sm text-gray-500 dark:border-white/[0.05] dark:bg-white/[0.03]">loading the terminal…</div>;

  const tone = (v: number) => (v > 0 ? "up" : v < 0 ? "down" : "flat");
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <Badge size="sm" color={s.pid ? (s.mode.includes("LIVE") ? "error" : "success") : "light"}>
          {s.mode}{s.pid ? ` · pid ${s.pid}` : ""}
        </Badge>
        {s.halted && <Badge size="sm" color="warning">HALTED — no new entries</Badge>}
        {sup && !s.pid && sup.wants_runner && (
          <Badge size="sm" color="error">
            DIED{sup.last_beat_seconds != null
              ? ` — last heartbeat ${Math.round(sup.last_beat_seconds / 60)} min ago`
              : ""}
          </Badge>
        )}
        {sup && s.pid && sup.stale && (
          <Badge size="sm" color="warning">
            no heartbeat for {Math.round((sup.last_beat_seconds ?? 0) / 60)} min
          </Badge>
        )}
        {sup && !sup.disk_ok && (
          <Badge size="sm" color="error">
            disk almost full — {sup.free_mb.toLocaleString()} MB free
          </Badge>
        )}
        {note && <span className="text-theme-xs font-medium text-error-500">{note}</span>}
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {s.pid
            ? <Button size="sm" variant="outline" disabled={busy} onClick={() => runner("stop")}>STOP RUNNER</Button>
            : <Button size="sm" disabled={busy} onClick={() => runner("start")}>START RUNNER</Button>}
          <Button size="sm" variant="outline" disabled={busy} onClick={halt}>
            {s.halted ? "RESUME ENTRIES" : "HALT ENTRIES"}
          </Button>
          <label className="flex items-center gap-1.5 text-theme-xs text-gray-600 dark:text-gray-300"
            title={sup?.installed
              ? `macOS restarts the runner within ${sup.throttle_seconds}s of a crash, while it is meant to be up. A deliberate STOP is respected.`
              : "off: if the runner dies, nothing brings it back"}>
            <input type="checkbox" checked={!!sup?.installed}
              onChange={async (e) => {
                setBusy(true);
                try { await tradeApi.setSupervisor(e.target.checked); await loadSup(); }
                catch (err) { setErr(String(err)); } finally { setBusy(false); }
              }}
              className="h-4 w-4 accent-brand-500" />
            auto-restart
          </label>
          <label className="flex items-center gap-1.5 text-theme-xs text-gray-600 dark:text-gray-300">
            <input type="checkbox" checked={armed} onChange={(e) => setArmed(e.target.checked)}
              className="h-4 w-4 accent-error-500" />
            arm PANIC
          </label>
          <button disabled={!armed || busy} onClick={panic}
            className="rounded-lg bg-error-500 px-3 py-2 text-theme-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40">
            PANIC — close all
          </button>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
        <Tile label="Futures wallet" value={s.equity == null ? "—" : s.equity.toLocaleString("en-US", { minimumFractionDigits: 2 })} sub="USDT collateral" />
        <Tile label="Real · all time" value={money(s.all_time)} sub={`${money(s.all_time_closed)} closed · ${money(s.open_unrealized)} open`} tone={tone(s.all_time)} />
        <Tile label="Real · today closed" value={money(s.today_real.total)} sub={`${s.today_real.wins}W / ${s.today_real.losses}L · ${s.today_real.trades} closed`} tone={tone(s.today_real.total)} />
        <Tile label="Open · unrealized" value={money(s.open_unrealized)} sub={`${s.open_positions.length} real position${s.open_positions.length === 1 ? "" : "s"}`} tone={tone(s.open_unrealized)} />
        <Tile label="Paper · today" value={money(s.today_paper.total)} sub={`${s.today_paper.wins}W / ${s.today_paper.losses}L`} tone={tone(s.today_paper.total)} />
        <Tile label="Paper · open" value={String(s.paper_positions.length)} sub="simulated positions" />
      </div>
    </div>
  );
}
