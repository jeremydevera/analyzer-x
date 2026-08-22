"use client";
/** Newly listed MEXC coins. The count line says what was scanned, what was
 * hidden and by which filter, and whether the sweep is cached or stale —
 * an empty table must never read as "nothing new" when it means
 * "could not check". */
import { useEffect, useState } from "react";
import { analysisApi, cryptoApi, NewCoinRow, ScreenPayload, UpcomingRow, fmtWhen, fmtWhenMs } from "@/lib/api";
import { useRouter } from "next/navigation";
import CoinChart from "./CoinChart";
import Badge from "@/components/ui/badge/Badge";
import Button from "@/components/ui/button/Button";
import { Table, TableBody, TableCell, TableHeader, TableRow } from "@/components/ui/table";

const input =
  "h-10 w-28 rounded-lg border border-gray-300 bg-transparent px-3 text-theme-sm text-gray-700 " +
  "focus:outline-hidden focus:ring-2 focus:ring-brand-500/20 dark:border-gray-700 dark:text-gray-300";

const vol = (v: number) =>
  v >= 1e9 ? `${(v / 1e9).toFixed(2)}B` : v >= 1e6 ? `${(v / 1e6).toFixed(2)}M` : v >= 1e3 ? `${(v / 1e3).toFixed(1)}K` : v.toFixed(0);

const age = (h: number) => (h < 24 ? `${h.toFixed(1)}h` : `${Math.floor(h / 24)}d ${Math.round(h % 24)}h`);

type SortKey = keyof Pick<NewCoinRow, "base" | "age_hours" | "change_pct" | "quote_volume" | "price">;

export default function NewCryptoScreen() {
  const [data, setData] = useState<ScreenPayload | null>(null);
  const [upcoming, setUpcoming] = useState<UpcomingRow[]>([]);
  const [upWhy, setUpWhy] = useState("");
  const [minVol, setMinVol] = useState(0);
  const [minAge, setMinAge] = useState(0);
  const [minUnit, setMinUnit] = useState<"h" | "d">("h");
  const [maxAge, setMaxAge] = useState(0);
  const [maxUnit, setMaxUnit] = useState<"h" | "d">("d");
  const [showAll, setShowAll] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [sort, setSort] = useState<SortKey>("age_hours");
  const [open, setOpen] = useState<NewCoinRow | null>(null);
  const [watch, setWatch] = useState(false);
  const [known, setKnown] = useState<string[]>([]);
  const [alerts, setAlerts] = useState<NewCoinRow[]>([]);
  const [lastTick, setLastTick] = useState(0);
  const [watchWhy, setWatchWhy] = useState("");
  const [loop, setLoop] = useState(false);
  const [analysing, setAnalysing] = useState("");
  const router = useRouter();
  const [asc, setAsc] = useState(true);

  const load = (refresh = false) => {
    setBusy(true);
    cryptoApi.newListings({
      min_volume: minVol || undefined,
      min_age_hours: minAge ? minAge * (minUnit === "d" ? 24 : 1) : undefined,
      max_age_hours: maxAge ? maxAge * (maxUnit === "d" ? 24 : 1) : undefined,
      include_all: showAll || undefined, refresh })
      .then((d) => { setData(d); setErr(""); })
      .catch((e) => setErr(String(e)))
      .finally(() => setBusy(false));
  };

  useEffect(() => {
    load();
    cryptoApi.upcoming().then((d) => { setUpcoming(d.rows); setUpWhy(d.why ?? ""); }).catch((e) => setUpWhy(String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The alarm is generated, not a bundled asset: a short WebAudio chirp, so
  // there is no file to lose and nothing is fetched from a CDN.
  const beep = () => {
    try {
      const AC = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      const ctx = new AC();
      const play = (at: number, f: number) => {
        const o = ctx.createOscillator(), g = ctx.createGain();
        o.frequency.value = f; o.type = "sine";
        g.gain.setValueAtTime(0.0001, ctx.currentTime + at);
        g.gain.exponentialRampToValueAtTime(0.25, ctx.currentTime + at + 0.02);
        g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + at + 0.35);
        o.connect(g); g.connect(ctx.destination);
        o.start(ctx.currentTime + at); o.stop(ctx.currentTime + at + 0.4);
      };
      [0, 0.45, 0.9].forEach((t, i) => play(t, 880 + i * 220));
    } catch { /* a blocked audio context must never break the page */ }
  };

  useEffect(() => {
    if (!watch) return;
    let alive = true;
    const tick = () =>
      cryptoApi.watch(known, 48).then((d) => {
        if (!alive) return;
        setKnown(d.known);
        setLastTick(Date.now());
        setWatchWhy(d.why);
        if (d.found.length) {
          setAlerts((a) => [...d.found, ...a].slice(0, 20));
          beep();
          if (loop) { setTimeout(beep, 1500); setTimeout(beep, 3000); }
          load();   // the sweep has just been told about them
        }
      }).catch((e) => alive && setWatchWhy(String(e)));
    tick();
    const t = setInterval(tick, 120000);   // 2 min, one request per tick
    return () => { alive = false; clearInterval(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [watch, known.length, loop]);

  const analyse = async (c: NewCoinRow) => {
    setAnalysing(c.base);
    try {
      const got = await analysisApi.startMany({
        ticker: c.base, trade_date: new Date().toISOString().slice(0, 10),
        analysts: ["market", "social", "news"], debate_rounds: 1, risk_rounds: 1,
        asset_type: "crypto", social_source: "stocktwits",
      });
      router.push(`/analysis?run=${got.run_id}`);
    } catch (e) { setErr(String(e)); } finally { setAnalysing(""); }
  };

  const rows = [...(data?.rows ?? [])].sort((a, b) => {
    const x = a[sort], y = b[sort];
    const c = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y));
    return asc ? c : -c;
  });
  const click = (k: SortKey) => { if (k === sort) setAsc(!asc); else { setSort(k); setAsc(k === "base" || k === "age_hours"); } };

  const filters = [
    minVol ? `volume ≥ ${vol(minVol)}` : "",
    minAge ? `age ≥ ${minAge}${minUnit}` : "",
    maxAge ? `age ≤ ${maxAge}${maxUnit}` : "",
    showAll ? "including dust" : "",
  ].filter(Boolean);

  return (
    <div className="flex flex-col gap-5">
      <div className="overflow-hidden rounded-2xl border border-gray-200 bg-white dark:border-white/[0.05] dark:bg-white/[0.03]">
        <div className="flex flex-wrap items-end gap-3 px-5 pt-4">
          <div>
            <h3 className="text-base font-semibold text-gray-800 dark:text-white/90">
              New on MEXC · last {data?.window_days ?? "—"} days
            </h3>
            <p className="text-theme-xs text-gray-500 dark:text-gray-400">
              {data
                ? <>
                    {rows.length} shown of {data.scanned.toLocaleString()} USDT pairs scanned
                    {data.hidden_by_volume ? ` · ${data.hidden_by_volume} hidden by volume` : ""}
                    {data.hidden_by_age ? ` · ${data.hidden_by_age} outside the age range` : ""}
                    {data.unresolved ? ` · ${data.unresolved} could NOT be dated` : ""}
                    {filters.length ? ` · filters: ${filters.join(" · ")}` : ""}
                  </>
                : "sweeping…"}
            </p>
          </div>
          <div className="ml-auto flex flex-wrap items-end gap-2">
            <label className="flex flex-col text-theme-xs text-gray-500 dark:text-gray-400">min volume $
              <input type="number" className={input} value={minVol || ""} onChange={(e) => setMinVol(Number(e.target.value))} /></label>
            <label className="flex flex-col text-theme-xs text-gray-500 dark:text-gray-400">age from
              <span className="flex gap-1">
                <input type="number" className={`${input} w-20`} value={minAge || ""} onChange={(e) => setMinAge(Number(e.target.value))} />
                <select className={`${input} w-16`} value={minUnit} onChange={(e) => setMinUnit(e.target.value as "h" | "d")}>
                  <option value="h">hours</option><option value="d">days</option>
                </select>
              </span></label>
            <label className="flex flex-col text-theme-xs text-gray-500 dark:text-gray-400">age to
              <span className="flex gap-1">
                <input type="number" className={`${input} w-20`} value={maxAge || ""} onChange={(e) => setMaxAge(Number(e.target.value))} />
                <select className={`${input} w-16`} value={maxUnit} onChange={(e) => setMaxUnit(e.target.value as "h" | "d")}>
                  <option value="h">hours</option><option value="d">days</option>
                </select>
              </span></label>
            <label className="flex h-10 items-center gap-2 text-theme-xs text-gray-600 dark:text-gray-300">
              <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} className="h-4 w-4 accent-brand-500" />
              show all (incl. dust)
            </label>
            <label className="flex h-10 items-center gap-2 text-theme-xs text-gray-600 dark:text-gray-300">
              <input type="checkbox" checked={watch} onChange={(e) => setWatch(e.target.checked)}
                className="h-4 w-4 accent-brand-500" />
              watch for new listings
            </label>
            {watch && (
              <label className="flex h-10 items-center gap-2 text-theme-xs text-gray-600 dark:text-gray-300">
                <input type="checkbox" checked={loop} onChange={(e) => setLoop(e.target.checked)}
                  className="h-4 w-4 accent-brand-500" />
                loop the alarm
              </label>
            )}
            {watch && (
              <button onClick={beep} className="h-10 rounded-lg border border-gray-200 px-2 text-theme-xs text-gray-600 dark:border-gray-700 dark:text-gray-300">
                test sound
              </button>
            )}
            <Button size="sm" disabled={busy} onClick={() => load(false)}>APPLY</Button>
            <Button size="sm" variant="outline" disabled={busy} onClick={() => load(true)}>FRESH SWEEP</Button>
          </div>
        </div>
        {data && (
          <p className="px-5 pt-2 text-theme-xs">
            {data.stale
              ? <span className="text-warning-600">This sweep is STALE — a refresh failed, so these are the last numbers that could be read ({fmtWhen(data.fetched_at)}).</span>
              : <span className="text-gray-500 dark:text-gray-400">{data.from_cache ? "cached" : "fresh"} sweep from {fmtWhen(data.fetched_at)}</span>}
          </p>
        )}
        {watch && (
          <p className="px-5 pt-2 text-theme-xs">
            {watchWhy
              ? <span className="text-warning-600">watch paused — {watchWhy}</span>
              : <span className="text-gray-500 dark:text-gray-400">
                  watching {known.length.toLocaleString()} pairs, one request every 2 min
                  {lastTick ? ` · last checked ${fmtWhenMs(lastTick)}` : " · seeding the baseline…"}
                  {alerts.length ? ` · ${alerts.length} alert(s) this session` : ""}
                </span>}
          </p>
        )}
        {alerts.length > 0 && (
          <div className="mx-5 mt-2 rounded-lg bg-success-50 px-3 py-2 text-theme-sm text-success-700 dark:bg-success-500/10">
            NEW: {alerts.map((a) => `${a.base} (${a.age_hours?.toFixed(1)}h old)`).join(" · ")}
          </div>
        )}
        {err && <p className="px-5 pt-2 text-theme-sm text-error-500">{err}</p>}
        <div className="max-h-[520px] max-w-full overflow-auto p-2">
          <Table>
            <TableHeader className="sticky top-0 bg-white dark:bg-gray-900">
              <TableRow>
                {([["coin", "base"], ["name", null], ["listed", null], ["age", "age_hours"], ["price", "price"], ["24h %", "change_pct"], ["24h volume $", "quote_volume"], ["contract", null]] as [string, SortKey | null][]).map(([h, k]) => (
                  <TableCell key={h} isHeader className="px-3 py-2 text-theme-xs font-medium text-gray-500 text-start dark:text-gray-400">
                    {k ? <button onClick={() => click(k)} className="hover:text-brand-500">{h}{sort === k ? (asc ? " ▲" : " ▼") : ""}</button> : h}
                  </TableCell>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
              {rows.map((c) => (
                <TableRow key={c.symbol} onClick={() => setOpen(open?.symbol === c.symbol ? null : c)}
                  className={`cursor-pointer hover:bg-gray-50 dark:hover:bg-white/[0.03] ${open?.symbol === c.symbol ? "bg-brand-50 dark:bg-brand-500/10" : ""}`}>
                  <TableCell className="px-3 py-2 text-theme-sm font-medium text-gray-800 dark:text-white/90">{c.base}</TableCell>
                  <TableCell className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{c.name}</TableCell>
                  <TableCell className="px-3 py-2 text-theme-xs text-gray-500 dark:text-gray-400">{c.listed_date}</TableCell>
                  <TableCell className="px-3 py-2 text-theme-xs text-gray-500 dark:text-gray-400">{age(c.age_hours)}</TableCell>
                  <TableCell className="px-3 py-2 text-theme-xs text-gray-700 dark:text-gray-300">{String(c.price)}</TableCell>
                  <TableCell className={`px-3 py-2 text-theme-sm font-medium ${c.change_pct >= 0 ? "text-success-600" : "text-error-500"}`}>{c.change_pct >= 0 ? "+" : ""}{c.change_pct.toFixed(2)}%</TableCell>
                  <TableCell className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{vol(c.quote_volume)}</TableCell>
                  <TableCell className="max-w-[200px] truncate px-3 py-2 font-mono text-theme-xs text-gray-400">{c.contract || "—"}</TableCell>
                </TableRow>
              ))}
              {data && !rows.length && (
                <TableRow><TableCell className="px-3 py-4 text-theme-sm text-gray-500 dark:text-gray-400">
                  {data.scanned
                    ? `No coin in the last ${data.window_days} days passed these filters — ${data.hidden_by_volume} were hidden by volume and ${data.hidden_by_age} by the age range.`
                    : "The sweep could not read the exchange, so this is NOT a claim that nothing is new."}
                </TableCell></TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </div>

      {open && (
        <div className="overflow-hidden rounded-2xl border border-gray-200 bg-white p-5 dark:border-white/[0.05] dark:bg-white/[0.03]">
          <div className="mb-3 flex flex-wrap items-center gap-3">
            <h3 className="text-base font-semibold text-gray-800 dark:text-white/90">{open.base} · {open.name}</h3>
            <span className="text-theme-xs text-gray-500 dark:text-gray-400">
              listed {open.listed_date} · {age(open.age_hours)} old · 24h volume {vol(open.quote_volume)}
            </span>
            <Button size="sm" className="ml-auto" disabled={analysing === open.base} onClick={() => analyse(open)}>
              {analysing === open.base ? "starting…" : "ANALYZE THIS COIN"}
            </Button>
          </div>
          <CoinChart symbol={`${open.base}_USDT`} />
          {open.contract && (
            <p className="mt-2 break-all font-mono text-theme-xs text-gray-400">contract {open.contract}</p>
          )}
        </div>
      )}

      <div className="overflow-hidden rounded-2xl border border-gray-200 bg-white dark:border-white/[0.05] dark:bg-white/[0.03]">
        <h3 className="px-5 pt-4 text-base font-semibold text-gray-800 dark:text-white/90">Announced, not trading yet</h3>
        <p className="px-5 text-theme-xs text-gray-500 dark:text-gray-400">
          {upWhy ? `schedule unavailable — ${upWhy}` : `${upcoming.length} listing${upcoming.length === 1 ? "" : "s"} the exchange has announced`}
        </p>
        <div className="max-h-64 max-w-full overflow-auto p-2">
          <Table>
            <TableBody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
              {upcoming.map((u) => (
                <TableRow key={u.symbol}>
                  <TableCell className="px-3 py-2 text-theme-sm font-medium text-gray-800 dark:text-white/90">{u.base}</TableCell>
                  <TableCell className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">{u.name}</TableCell>
                  <TableCell className="px-3 py-2 text-theme-xs text-gray-500 dark:text-gray-400">
                    {u.open_ms ? fmtWhenMs(u.open_ms) : "time not published"}
                  </TableCell>
                  <TableCell className="px-3 py-2 text-theme-xs">
                    {u.hours_until != null
                      ? <Badge size="sm" color={u.hours_until < 24 ? "warning" : "light"}>{u.hours_until.toFixed(1)}h away</Badge>
                      : <span className="text-gray-400">—</span>}
                  </TableCell>
                </TableRow>
              ))}
              {!upcoming.length && !upWhy && (
                <TableRow><TableCell className="px-3 py-4 text-theme-sm text-gray-500 dark:text-gray-400">Nothing announced right now.</TableCell></TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </div>
    </div>
  );
}
