"use client";
/**
 * Run backtests. Downloading candles lives on its own screen — this one is
 * for backtesting only, so a multi-hour download is never one click from a
 * grid run.
 *
 * Progress polls every 4s and survives reloads because the truth lives in the
 * job's progress file on disk, not in this component.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { api, API_BASE, CloudStatus, GridPlan, JobStatus } from "@/lib/api";
import Button from "@/components/ui/button/Button";
import Badge from "@/components/ui/badge/Badge";
import JobProgress from "@/components/jobs/JobProgress";
import CoinPicker from "./CoinPicker";

const TFS = ["15m", "30m", "1h", "4h", "1d"];
const WINDOWS: Record<string, number> = {
  "Previous month": 30, "Previous 2 months": 60, "Previous 3 months": 90,
  "Previous 6 months": 180, "Previous 1 year": 365,
};
const inputCls =
  "h-10 w-full rounded-lg border border-gray-300 bg-transparent px-3 " +
  "text-theme-sm text-gray-700 focus:outline-hidden focus:ring-2 " +
  "focus:ring-brand-500/20 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-300";

export default function JobsPanel() {
  const [coins, setCoins] = useState<string[]>([]);
  const [tfs, setTfs] = useState<string[]>(["15m", "30m", "1h", "4h"]);
  const [win, setWin] = useState("Previous 1 year");
  const [bt, setBt] = useState<JobStatus | null>(null);
  const [upd, setUpd] = useState<JobStatus | null>(null);
  const [hand, setHand] = useState<Awaited<ReturnType<typeof api.jobHandoffState>> | null>(null);
  const [handing, setHanding] = useState(false);
  const [base, setBase] = useState(5);
  const [plan, setPlan] = useState<GridPlan | null>(null);
  const [deployed, setDeployed] = useState<{ coin: string; tf: string; key: string }[]>([]);
  const [where, setWhere] = useState<"mac" | "github">("mac");
  const [cloud, setCloud] = useState<CloudStatus | null>(null);
  const [err, setErr] = useState("");
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const poll = useCallback(() => {
    api.jobStatus("backtest").then(setBt).catch(() => {});
    api.jobStatus("btupdate").then(setUpd).catch(() => {});
    api.cloudStatus().then(setCloud).catch(() => {});
    api.jobHandoffState("backtest").then(setHand).catch(() => {});
  }, []);

  useEffect(() => {
    poll();
    timer.current = setInterval(poll, 4000);
    return () => { if (timer.current) clearInterval(timer.current); };
  }, [poll]);

  useEffect(() => {
    if (!coins.length || !tfs.length) { setPlan(null); setDeployed([]); return; }
    api.plan(coins, tfs).then(setPlan).catch(() => setPlan(null));
    api.deployedRows(coins, tfs).then((d) => setDeployed(d.rows)).catch(() => setDeployed([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [coins.join(","), tfs.join(",")]);

  const startCloud = async () => {
    setErr("");
    try {
      // the same window as the local job, or the two stores are not one measurement
      await api.cloudDispatch({ shards: 20, coins: coins.length, timeframes: tfs.join(","), days: WINDOWS[win] });
      api.cloudStatus().then(setCloud).catch(() => {});
    } catch (e) { setErr(String(e)); }
  };

  const handOff = async () => {
    setErr(""); setHanding(true);
    try {
      await api.jobHandoff("backtest");
      api.jobHandoffState("backtest").then(setHand).catch(() => {});
    } catch (e) { setErr(String(e)); } finally { setHanding(false); }
  };

  const start = async (kind: "backtest" | "btupdate") => {
    setErr("");
    try {
      await api.jobStart(kind, {
          coins, tfs, days: WINDOWS[win], base,
          label: "react", deployed,
          // BACKTEST = from scratch, UPDATE = fill the gap. Sent explicitly so
          // the button and the run agree without relying on a server default.
          fresh: kind === "backtest",
        });
      poll();
    } catch (e) {
      setErr(String(e));
    }
  };

  return (
    <div className="overflow-hidden rounded-2xl border border-gray-200 bg-white p-5 dark:border-white/[0.05] dark:bg-white/[0.03]">
      <h3 className="text-base font-semibold text-gray-800 dark:text-white/90">Backtest</h3>
      <p className="mb-4 text-theme-xs text-gray-500 dark:text-gray-400">
        Every signal × barrier pair × both sizings, over the candles already stored on this Mac.
        Runs detached — leaving this screen does not stop it. Candles are downloaded on the{" "}
        <a href="/candles" className="text-brand-500 hover:underline">Candles</a> screen.
      </p>
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="sm:col-span-1">
          <label className="mb-1 block text-theme-xs text-gray-500 dark:text-gray-400">Coins</label>
          <CoinPicker value={coins} onChange={setCoins} />
        </div>
        <div>
          <label className="mb-1 block text-theme-xs text-gray-500 dark:text-gray-400">Timeframes</label>
          <div className="flex flex-wrap gap-2 pt-1.5">
            {TFS.map((t) => (
              <button
                key={t}
                onClick={() => setTfs((cur) => cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t])}
                className={`rounded-full px-3 py-1 text-theme-xs font-medium ${tfs.includes(t)
                  ? "bg-brand-500 text-white"
                  : "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300"}`}
              >
                {t}
              </button>
            ))}
          </div>
        </div>
        <div>
          <label className="mb-1 block text-theme-xs text-gray-500 dark:text-gray-400">Window</label>
          <select className={inputCls} value={win} onChange={(e) => setWin(e.target.value)}>
            {Object.keys(WINDOWS).map((w) => <option key={w}>{w}</option>)}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-theme-xs text-gray-500 dark:text-gray-400">
            Base margin $ — every dollar figure is measured at this stake
          </label>
          <input type="number" min={1} step={1} className={inputCls} value={base}
            onChange={(e) => setBase(Number(e.target.value) || 1)} />
        </div>
        <div className="sm:col-span-2">
          <label className="mb-1 block text-theme-xs text-gray-500 dark:text-gray-400">Run where</label>
          <div className="flex gap-2 pt-1.5">
            {([["mac", "this Mac"], ["github", "GitHub Actions"]] as const).map(([k, lab]) => (
              <button key={k} onClick={() => setWhere(k)}
                className={`rounded-full px-3 py-1 text-theme-xs font-medium ${where === k
                  ? "bg-brand-500 text-white" : "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300"}`}>
                {lab}
              </button>
            ))}
            {where === "github" && (
              <span className="self-center text-theme-xs text-gray-500 dark:text-gray-400">
                {cloud?.available
                  ? "their machines run the same grid; rows come back in an artifact you merge into this Mac"
                  : `unavailable — ${cloud?.why ?? "checking…"}`}
              </span>
            )}
          </div>
        </div>
      </div>

      {plan && (
        <p className="mt-3 text-theme-xs text-gray-500 dark:text-gray-400">
          {plan.signals} signals × {plan.barrier_pairs} barrier pairs × {plan.sizings} sizings ×{" "}
          {plan.tfs} timeframe(s) × {plan.coins} coin(s) ={" "}
          <b>~{plan.combinations.toLocaleString()} combinations</b>, about {plan.eta_minutes} min with warm
          candles (up to 3× on the first run of the day). {plan.note}.
          {deployed.length > 0 && (
            <> <b>{deployed.length} live row(s)</b> will be injected and marked DEPLOYED:{" "}
              {deployed.map((d) => `${d.coin} ${d.tf} ${d.key}`).join(", ")}.</>
          )}
        </p>
      )}
      {err && <p className="mt-2 text-theme-sm text-error-500">{err}</p>}

      <div className="mt-4">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            {where === "github" ? (
              <Button size="sm" onClick={startCloud}
                disabled={!coins.length || !tfs.length || !cloud?.available}>
                RUN ON GITHUB
              </Button>
            ) : (
              <>
                <span title="FROM SCRATCH — every combination replays from its first candle. Slower; use UPDATE BACKTEST to only add new candles.">
                  <Button size="sm" onClick={() => start("backtest")}
                    disabled={!coins.length || !tfs.length || !!bt?.running}>
                    BACKTEST
                  </Button>
                </span>
                <span title="CONTINUE the stored backtests over new candles only — never from scratch.">
                  <Button size="sm" variant="outline" onClick={() => start("btupdate")}
                    disabled={!coins.length || !tfs.length || !!upd?.running}>
                    UPDATE BACKTEST
                  </Button>
                </span>
              </>
            )}
            {bt?.running && (
              <Button size="sm" variant="outline" onClick={() => api.jobStop("backtest").then(poll)}>STOP</Button>
            )}
            {/* Hand over WITHOUT losing anything: the local job finishes the
                pairs it is measuring, then the cloud takes the coins the Mac
                never reached. A plain STOP would leave those coins to nobody. */}
            {/* ALWAYS shown while a sweep runs. It used to hide itself when
                GitHub was unreachable, so the control simply vanished and the
                operator had no way to tell whether it had worked, broken, or
                never existed. A button that cannot act says why. */}
            {bt?.running && !hand?.requested && (
              <span title={hand?.available
                ? "Finish the pairs being measured right now, then dispatch GitHub Actions for the coins this Mac has not reached. Nothing already measured is re-run or overwritten."
                : `Cannot hand over yet: ${hand?.why?.split("\n")[0] ?? "checking GitHub…"}`}>
                <Button size="sm" variant="outline" onClick={handOff}
                        disabled={handing || !hand?.available}>
                  {handing ? "HANDING OVER…" : "SWITCH TO GITHUB ACTIONS"}
                </Button>
              </span>
            )}
            {hand?.requested && !hand?.stalled && (
              <Badge size="sm" color="warning">
                finishing the current pairs, then handing over
              </Badge>
            )}
            {hand?.stalled && (
              <Badge size="sm" color="error">hand-off is stuck</Badge>
            )}
            {upd?.running && (
              <Button size="sm" variant="outline" onClick={() => api.jobStop("btupdate").then(poll)}>STOP UPDATE</Button>
            )}
            {bt?.running && (
              <Badge size="sm" color="info">
                {/* DERIVED from the run, not a literal: a resumed job wearing a
                    "from scratch" badge is a false label on true data. */}
                full grid {bt.fresh === false ? "· gap fill" : bt.fresh ? "· from scratch" : ""}
              </Badge>
            )}
            {upd?.running && <Badge size="sm" color="info">update running</Badge>}
          </div>
          {hand?.stalled && (
            <p className="mt-2 text-theme-xs text-error-500">
              {hand.stalled_why}
            </p>
          )}
          {bt?.running && hand && !hand.available && (
            <p className="mt-2 text-theme-xs text-warning-600">
              SWITCH TO GITHUB ACTIONS is disabled: {hand.why.split("\n")[0]}
              {hand.why.includes("gh auth refresh")
                ? " — run `gh auth refresh -h github.com` in a terminal to fix it."
                : ""}
            </p>
          )}
          <JobProgress s={bt}
            label={`full grid${bt?.fresh === false ? " · gap fill"
                     : bt?.fresh ? " · from scratch" : ""}`} />
          <JobProgress s={upd} label="update · new candles only" />
        </div>
      </div>

      {where === "github" && cloud?.run?.id && (
        <div className="mt-4 rounded-xl border border-gray-200 p-3 dark:border-white/[0.08]">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-theme-sm font-medium text-gray-800 dark:text-white/90">
              GitHub run #{cloud.run.id}
            </span>
            <Badge size="sm" color={cloud.conclusion ? "success" : "info"}>
              {cloud.conclusion ?? "running"}
            </Badge>
            {(() => {
              const done = cloud.shards.reduce((a, s) => a + (s.done ?? 0), 0);
              const total = cloud.shards.reduce((a, s) => a + (s.total ?? 0), 0);
              const rows = cloud.shards.reduce((a, s) => a + (s.rows ?? 0), 0);
              const fin = cloud.shards.filter((s) => s.stage === "done").length;
              return (
                <>
                  <span className="text-theme-sm font-semibold text-brand-600 dark:text-brand-400 tabular-nums">
                    {total ? ((100 * done) / total).toFixed(1) : "0.0"}%
                  </span>
                  <span className="text-theme-xs text-gray-500 dark:text-gray-400">
                    {done.toLocaleString()}/{total.toLocaleString()} coins ·{" "}
                    {rows.toLocaleString()} rows measured ·{" "}
                    {fin}/{cloud.shards.length} machine(s) finished
                  </span>
                </>
              );
            })()}
            <div className="ml-auto flex gap-2">
              {!cloud.conclusion && (
                <Button size="sm" variant="outline"
                  onClick={() => api.cloudCancel(cloud.run!.id!).then(() => api.cloudStatus().then(setCloud))}>
                  CANCEL RUN
                </Button>
              )}
              {cloud.conclusion === "success" && (
                <Button size="sm"
                  onClick={() => api.cloudMerge(cloud.run!.id!).then((r) => setErr(`merged ${r.fetched} rows into this Mac`))}>
                  MERGE INTO THIS MAC
                </Button>
              )}
              <Button size="sm" variant="outline"
                onClick={() => api.cloudForget().then(() => setCloud({ ...cloud, run: null, shards: [] }))}>
                DISMISS
              </Button>
            </div>
          </div>
          {/* one bar for the RUN, so the answer to "how far along?" is not
              twenty tiles added up by eye */}
          {(() => {
            const done = cloud.shards.reduce((a, s) => a + (s.done ?? 0), 0);
            const total = cloud.shards.reduce((a, s) => a + (s.total ?? 0), 0);
            const pct = total ? (100 * done) / total : 0;
            return (
              <div className="mt-2 h-2 rounded-full bg-gray-200 dark:bg-gray-800">
                <div className="h-2 rounded-full bg-brand-500 transition-[width]"
                     style={{ width: `${pct.toFixed(1)}%` }} />
              </div>
            );
          })()}
          {/* Why the tiles can be EMPTY while the run is fine: this panel reads
              the shards through GitHub's Actions API, which secondary-limits a
              polling client (403 "API rate limit exceeded" at 9:59pm on
              2026-09-02 while all 20 machines were working). An empty list is
              not "nothing is running". */}
          {!cloud.shards.length && (
            <p className="mt-2 text-theme-xs text-warning-600 dark:text-warning-400">
              no machine has reported through GitHub&apos;s API yet
              {cloud.why ? ` — ${cloud.why}` : ""}. The run itself keeps going:
              the machines publish progress to the <b>sweep-progress</b> branch,
              and GitHub rate-limits this panel&apos;s polling long before it
              stops the work.
            </p>
          )}
          <div className="mt-2 grid gap-1 sm:grid-cols-2 lg:grid-cols-4">
            {cloud.shards.map((sh) => (
              <div key={sh.shard} className="rounded-lg bg-gray-50 px-2 py-1.5 dark:bg-white/[0.03]">
                <div className="flex justify-between text-theme-xs text-gray-600 dark:text-gray-300">
                  <span>machine {sh.shard}</span><span>{sh.pct ?? 0}%</span>
                </div>
                <div className="mt-1 h-1.5 rounded-full bg-gray-200 dark:bg-gray-800">
                  <div className="h-1.5 rounded-full bg-brand-500" style={{ width: `${sh.pct ?? 0}%` }} />
                </div>
                <p className="mt-0.5 truncate text-theme-xs text-gray-500 dark:text-gray-400">
                  {sh.stage ?? "waiting"}{sh.note ? ` · ${sh.note}` : ""}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
