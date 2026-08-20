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

export default function SummaryRibbon({ onSummary }: { onSummary?: (s: TradeSummary) => void }) {
  const [s, setS] = useState<TradeSummary | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () =>
    tradeApi.summary().then((d) => { setS(d); setErr(""); onSummary?.(d); }).catch((e) => setErr(String(e)));

  useEffect(() => {
    load();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const runner = async (action: "start" | "stop") => {
    if (action === "stop" && !confirm("Stop the runner? Open positions keep their exchange-side brackets, but no new trades will be taken.")) return;
    setBusy(true);
    try {
      if (action === "start") await tradeApi.runnerStart();
      else await tradeApi.runnerStop();
      await load();
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
        {s.halted && <Badge size="sm" color="warning">HALTED — daily loss limit</Badge>}
        <div className="ml-auto flex gap-2">
          {s.pid
            ? <Button size="sm" variant="outline" disabled={busy} onClick={() => runner("stop")}>STOP RUNNER</Button>
            : <Button size="sm" disabled={busy} onClick={() => runner("start")}>START RUNNER</Button>}
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
