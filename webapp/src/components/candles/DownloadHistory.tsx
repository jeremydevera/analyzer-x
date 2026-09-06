"use client";
/** What still needs doing, and every download this machine has run.
 *
 * Operator, 2026-09-02: *"this ui is very confusing, i dont know if there are
 * still errors or not fix this, if there are unfinished or error or pending on
 * my side, put that in the tab 'Pending'"*.
 *
 * The panel was answering the wrong question. Its tabs counted RUNS that had
 * failed at some point — a run that failed in August is not a thing to do in
 * September — and it drew a delisted contract in red as if a retry would help,
 * so one row read "FAILED · RESOLVED" beside "4 pairs still lost".
 *
 * PENDING answers "is there anything for me to do", from the store and the
 * venue as they are NOW, and it says which button fixes each thing. On the
 * store this was written against: 26 pairs sat on the lost list and 25 of them
 * were the venue serving no candles at all, which no retry can change. One was
 * a real retry. "26 still lost" had been reading as 26 problems.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api, DownloadHistory as Payload, DownloadHistoryRow, notifyApi,
} from "@/lib/api";

// the shapes come from the calls themselves, so a route change is a type error
// here rather than a silently-undefined field on the screen
type LostPayload = Awaited<ReturnType<typeof api.candleLost>>;
type CompPayload = Awaited<ReturnType<typeof api.candleCompleteness>>;
type GapsPayload = Awaited<ReturnType<typeof api.candleGaps>>;
type PendingPayload = Awaited<ReturnType<typeof api.candlePending>>;

const TF_ORDER = ["15m", "30m", "1h", "4h", "1d"];

/** One entry per (contract, reason), listing the timeframes it hit. */
function groupBy(items: { coin: string; tf: string; why: string }[]) {
  const by = new Map<string, { coin: string; why: string; tfs: string[] }>();
  for (const { coin, tf, why } of items) {
    const key = `${coin}|${why}`;
    const got = by.get(key) ?? { coin, why, tfs: [] };
    if (tf && !got.tfs.includes(tf)) got.tfs.push(tf);
    by.set(key, got);
  }
  return [...by.values()].map((g) => ({
    ...g,
    tfs: g.tfs.sort((a, b) => TF_ORDER.indexOf(a) - TF_ORDER.indexOf(b)),
  }));
}

function Chips({ items, tone, limit = 8 }: {
  items: { coin: string; why: string; tfs: string[] }[];
  tone: "bad" | "warn" | "mute" | "good";
  limit?: number;
}) {
  const [open, setOpen] = useState(false);
  const cls = {
    bad: "bg-error-50 text-error-700 dark:bg-error-500/15 dark:text-error-400",
    warn: "bg-warning-50 text-warning-700 dark:bg-warning-500/15 dark:text-warning-400",
    mute: "bg-gray-100 text-gray-600 dark:bg-white/[0.06] dark:text-gray-300",
    good: "bg-success-50 text-success-700 dark:bg-success-500/15 dark:text-success-400",
  }[tone];
  const shown = open ? items : items.slice(0, limit);
  return (
    <div className="mt-1 flex flex-wrap items-baseline gap-1">
      {shown.map((g) => (
        <span key={`${g.coin}-${g.why}`} className={`rounded px-1.5 py-0.5 text-[11px] ${cls}`}>
          <b className="font-semibold">{g.coin.replace("_USDT", "")}</b>
          {g.tfs.length ? ` ${g.tfs.length === TF_ORDER.length ? "all 5" : g.tfs.join(" ")}` : ""}
        </span>
      ))}
      {items.length > limit && (
        <button onClick={() => setOpen(!open)}
          className="text-[11px] font-medium text-brand-500 hover:underline">
          {open ? "show fewer" : `+${items.length - limit} more`}
        </button>
      )}
    </div>
  );
}

/** One thing that needs doing, what fixes it, and what it is. */
function Job({ tone, what, fix, children }: {
  tone: "bad" | "warn" | "mute"; what: string; fix: string;
  children?: React.ReactNode;
}) {
  const dot = { bad: "bg-error-500", warn: "bg-warning-500", mute: "bg-gray-400" }[tone];
  return (
    <li className="border-b border-gray-50 pb-2 last:border-0 dark:border-gray-800/60">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${dot}`} />
        <span className="text-theme-sm font-medium text-gray-800 dark:text-white/90">{what}</span>
        <span className="text-theme-xs text-gray-500 dark:text-gray-400">— {fix}</span>
      </div>
      {children}
    </li>
  );
}

function Pending({ refreshKey }: { refreshKey: number }) {
  const [lost, setLost] = useState<LostPayload | null>(null);
  const [comp, setComp] = useState<CompPayload | null>(null);
  const [gaps, setGaps] = useState<GapsPayload | null>(null);
  // THE count, from the route. This component used to add it up itself
  // (`retry.length + missing.length + behind`) while the RESOLVE button read a
  // different field, so one screen carried two answers to one question.
  const [work, setWork] = useState<PendingPayload | null>(null);
  const [why, setWhy] = useState("");

  useEffect(() => {
    api.candleLost().then(setLost).catch((e) => setWhy(String(e)));
    api.candleCompleteness().then(setComp).catch(() => {});
    api.candleGaps().then(setGaps).catch(() => {});
    api.candlePending().then(setWork).catch(() => {});
  }, [refreshKey]);

  const byKind = useMemo(() => {
    const out: Record<string, { coin: string; tf: string; why: string }[]> = {};
    for (const p of lost?.pairs ?? []) {
      const kind = p.kind ?? "retry";
      (out[kind] ??= []).push({
        coin: p.symbol, tf: p.timeframe,
        why: kind === "empty" ? "the venue serves no candles" : kind,
      });
    }
    return out;
  }, [lost]);

  const retry = byKind.retry ?? [];
  const empty = byKind.empty ?? [];
  const gone = byKind.delisted ?? [];
  const missing = (comp?.missing ?? []).map((p) => ({
    coin: p.symbol, tf: p.timeframe, why: "never stored",
  }));
  const behind = gaps?.behind ?? 0;

  // Only the things a BUTTON on this screen can change count as pending —
  // counted by the ROUTE, so this number and the RESOLVE button's are one
  // number. While it is still loading, fall back to what is on screen.
  const jobs = work ? work.count : retry.length + missing.length + behind;

  if (why) {
    return <p className="mt-3 text-theme-xs text-error-500">could not read the store: {why}</p>;
  }
  if (!lost && !comp && !gaps) {
    return <p className="mt-3 text-theme-xs text-gray-500 dark:text-gray-400">reading the store…</p>;
  }

  return (
    <>
      <p className={`mt-3 text-theme-sm font-medium ${
        jobs ? "text-warning-600 dark:text-warning-400" : "text-success-600 dark:text-success-400"}`}>
        {/* WHAT THE NUMBER MEANS, not just the number. "5,095 pending" reads
            as 5,095 problems; it means "your candles are 12.6 hours old". The
            count climbs back to ~5,000 within hours of ANY run, because every
            stored pair is behind again as soon as a bar prints — it was 0 at
            10:55pm and 5,095 by 9:33am with nothing wrong (2026-09-06). A
            count that resets nightly is a clock, not a to-do list. */}
        {jobs
          ? (work?.behind && work.behind_hours
              ? `your candles are ${work.behind_hours}h behind — ${jobs.toLocaleString()} pair${jobs === 1 ? "" : "s"} to top up`
              : `${jobs.toLocaleString()} thing${jobs === 1 ? "" : "s"} a run would fix`)
            + (work?.missing
              ? ` · ${work.missing.toLocaleString()} never stored`
              : "")
            + (work?.unfixable
              ? ` · ${work.unfixable.toLocaleString()} more nothing can`
              : "")
          : "nothing pending — every contract the venue serves is stored and current"}
        {/* HOW OLD this number is. Every count here comes from the candle
            index, so a stale index is a stale count — on 2026-09-05 a resolve
            stored 73,299 bars with zero errors while this figure went UP,
            because the index behind it was 27 minutes old. */}
        {(work?.index_age_s ?? 0) > 300 && (
          <span className="ml-2 font-normal text-theme-xs text-warning-600 dark:text-warning-400">
            · counted from an index {Math.round((work!.index_age_s ?? 0) / 60)} min old,
            so a running job&apos;s work is not in it yet
          </span>
        )}
        {jobs > 0 && (
          <span className="ml-2 font-normal text-theme-xs text-gray-500 dark:text-gray-400">
            press <b>RESOLVE {jobs.toLocaleString()} PENDING</b> — it does all of them in one run
          </span>
        )}
      </p>
      <ul className="mt-2 flex flex-col gap-2">
        {behind > 0 && (
          <Job tone="warn" fix="press UPDATE CANDLES"
            what={`${behind.toLocaleString()} pair${behind === 1 ? "" : "s"} behind by more than a bar`}>
            {gaps?.worst && (
              <p className="text-theme-xs text-gray-500 dark:text-gray-400">
                furthest behind: {gaps.worst.symbol.replace("_USDT", "")} {gaps.worst.timeframe},{" "}
                {gaps.worst.hours_behind?.toFixed(1)}h · last bar {gaps.worst.last}
              </p>
            )}
          </Job>
        )}
        {missing.length > 0 && (
          <Job tone="warn" fix="press UPDATE CANDLES — it fetches these too"
            what={`${missing.length} pair${missing.length === 1 ? "" : "s"} the store has never had`}>
            <Chips items={groupBy(missing)} tone="warn" />
          </Job>
        )}
        {retry.length > 0 && (
          <Job tone="bad" fix="press RETRY FAILED"
            what={`${retry.length} pair${retry.length === 1 ? "" : "s"} a retry would fetch`}>
            <Chips items={groupBy(retry)} tone="bad" />
          </Job>
        )}
        {empty.length > 0 && (
          <Job tone="mute" fix="nothing to do: a retry gets the same empty answer"
            what={`${empty.length} pair${empty.length === 1 ? "" : "s"} the venue serves no candles for`}>
            <Chips items={groupBy(empty)} tone="mute" />
          </Job>
        )}
        {gone.length > 0 && (
          <Job tone="mute" fix="nothing can fetch a contract MEXC has dropped"
            what={`${gone.length} pair${gone.length === 1 ? "" : "s"} on delisted contracts`}>
            <Chips items={groupBy(gone)} tone="mute" />
          </Job>
        )}
        {(gaps?.delisted_count ?? 0) > 0 && (
          <Job tone="mute" fix="not counted above — nothing can fetch them"
            what={`${gaps!.delisted_count} stored pair${gaps!.delisted_count === 1 ? "" : "s"} on delisted contracts`} />
        )}
      </ul>
    </>
  );
}

function Run({ r }: { r: DownloadHistoryRow }) {
  const [open, setOpen] = useState(false);
  const lost = r.lost ?? [];
  const groups = useMemo(() => {
    const kinds: Record<string, { coin: string; tf: string; why: string }[]> = {};
    for (const p of lost) {
      const kind = p.recovered ? "recovered" : (p.kind ?? "retry");
      (kinds[kind] ??= []).push({
        coin: p.symbol, tf: p.timeframe, why: kind,
      });
    }
    return kinds;
  }, [lost]);
  const still = (groups.retry ?? []).length;
  const empty = (groups.empty ?? []).length;
  const gone = (groups.delisted ?? []).length;
  const back = (groups.recovered ?? []).length;

  return (
    <li className="border-b border-gray-50 pb-2 last:border-0 dark:border-gray-800/60">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase ${
          r.stopped
            ? "bg-gray-100 text-gray-500 dark:bg-white/[0.06] dark:text-gray-400"
            : r.ok
              ? "bg-success-50 text-success-700 dark:bg-success-500/15 dark:text-success-400"
              : "bg-error-50 text-error-700 dark:bg-error-500/15 dark:text-error-400"}`}>
          {r.stopped ? "stopped" : r.ok ? "success" : "failed"}
        </span>
        <span className="font-mono text-theme-xs text-gray-700 dark:text-gray-300">
          {(r.bars ?? 0).toLocaleString()} bars
        </span>
        <span className="text-theme-xs text-gray-500 dark:text-gray-400">
          {(r.pairs ?? 0).toLocaleString()} pair{r.pairs === 1 ? "" : "s"} · {r.mode}
          {r.errors ? ` · ${r.errors} error${r.errors === 1 ? "" : "s"}` : ""}
        </span>
        <span className="ml-auto text-theme-xs text-gray-400 dark:text-gray-500">{r.when}</span>
      </div>

      {/* what those errors WERE, in one line, by what could be done about them */}
      {!r.ok && lost.length > 0 && (
        <p className="mt-1 text-theme-xs">
          {still ? <span className="text-error-500">{still} to retry</span> : null}
          {still && (empty || gone || back) ? <span className="text-gray-400"> · </span> : null}
          {empty ? (
            <span className="text-gray-500 dark:text-gray-400">
              {empty} the venue serves nothing for
            </span>
          ) : null}
          {empty && (gone || back) ? <span className="text-gray-400"> · </span> : null}
          {gone ? (
            <span className="text-gray-500 dark:text-gray-400">{gone} delisted since</span>
          ) : null}
          {gone && back ? <span className="text-gray-400"> · </span> : null}
          {back ? (
            <span className="text-success-600 dark:text-success-400">{back} stored since</span>
          ) : null}
          {r.unnamed ? (
            <span className="text-gray-500 dark:text-gray-400">
              {" · "}{r.unnamed} not named by that run
            </span>
          ) : null}
          <button onClick={() => setOpen(!open)}
            className="ml-2 text-[11px] font-medium text-brand-500 hover:underline">
            {open ? "hide" : "which ones"}
          </button>
        </p>
      )}

      {open && (
        <div className="mt-1 rounded-lg bg-gray-50 p-2 dark:bg-white/[0.03]">
          {r.detail && (
            <p className="break-words text-theme-xs text-gray-600 dark:text-gray-300">{r.detail}</p>
          )}
          {(["retry", "empty", "delisted", "recovered"] as const).map((kind) =>
            (groups[kind] ?? []).length ? (
              <div key={kind}>
                <p className="mt-1 text-[10px] font-semibold uppercase text-gray-400">
                  {kind === "retry" ? "a retry would fetch these"
                    : kind === "empty" ? "the venue serves no candles for these"
                      : kind === "delisted" ? "delisted — nothing can fetch these"
                        : "in the store since"}
                </p>
                <Chips items={groupBy(groups[kind])}
                  tone={kind === "retry" ? "bad" : kind === "recovered" ? "good" : "mute"}
                  limit={40} />
              </div>
            ) : null)}
        </div>
      )}
    </li>
  );
}

const TABS = [
  { id: "pending", label: "pending" },
  { id: "fail", label: "failed runs" },
  { id: "ok", label: "clean runs" },
] as const;
type Tab = (typeof TABS)[number]["id"];

export default function DownloadHistory({ refreshKey = 0 }: { refreshKey?: number }) {
  const [d, setD] = useState<Payload | null>(null);
  const [tab, setTab] = useState<Tab>("pending");

  const load = useCallback(() => {
    notifyApi.downloadHistory(20).then(setD).catch(() => {});
  }, []);
  useEffect(() => { load(); }, [load, refreshKey]);

  const runs = useMemo(
    () => (d?.rows ?? []).filter((r) => (tab === "ok" ? r.ok : !r.ok)),
    [d, tab],
  );

  return (
    <div className="mt-5 rounded-2xl border border-gray-200 bg-white p-5 dark:border-white/[0.05] dark:bg-white/[0.03]">
      <div className="flex flex-wrap items-baseline gap-2">
        <h4 className="text-sm font-semibold text-gray-800 dark:text-white/90">Candle store</h4>
        <span className="text-theme-xs text-gray-500 dark:text-gray-400">
          {d ? `${d.total} download${d.total === 1 ? "" : "s"} run on this PC` : ""}
        </span>
        <div className="ml-auto flex gap-1">
          {TABS.map((t) => (
            <button key={t.id} onClick={() => setTab(t.id)}
              aria-current={tab === t.id ? "true" : undefined}
              className={`rounded-lg px-2.5 py-1 text-theme-xs font-medium ${
                tab === t.id
                  ? "bg-brand-50 text-brand-600 dark:bg-brand-500/15 dark:text-brand-400"
                  : "text-gray-500 hover:bg-gray-50 dark:text-gray-400 dark:hover:bg-white/[0.05]"}`}>
              {t.label}
              {t.id === "fail" && d?.failed ? ` ${d.failed}` : ""}
              {t.id === "ok" && d?.ok ? ` ${d.ok}` : ""}
            </button>
          ))}
        </div>
      </div>

      {tab === "pending" ? (
        <Pending refreshKey={refreshKey} />
      ) : runs.length ? (
        <>
          {/* a past run is history, not a job — say so once, here */}
          <p className="mt-2 text-theme-xs text-gray-400 dark:text-gray-500">
            what already happened. What still needs doing is in <b>pending</b>.
          </p>
          <ul className="mt-2 flex flex-col gap-2">
            {runs.map((r) => <Run key={r.ts} r={r} />)}
          </ul>
        </>
      ) : (
        <p className="mt-3 text-theme-xs text-gray-500 dark:text-gray-400">
          {tab === "fail"
            ? "no download has ever failed on this PC"
            : "no download has finished clean yet"}
        </p>
      )}
    </div>
  );
}
