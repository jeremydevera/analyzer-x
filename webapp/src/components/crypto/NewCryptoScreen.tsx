"use client";
/** Newly listed MEXC coins. The count line says what was scanned, what was
 * hidden and by which filter, and whether the sweep is cached or stale —
 * an empty table must never read as "nothing new" when it means
 * "could not check". */
import { useEffect, useState } from "react";
import { cryptoApi, NewCoinRow, ScreenPayload, UpcomingRow } from "@/lib/api";
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
  const [maxAge, setMaxAge] = useState(0);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [sort, setSort] = useState<SortKey>("age_hours");
  const [asc, setAsc] = useState(true);

  const load = (refresh = false) => {
    setBusy(true);
    cryptoApi.newListings({ min_volume: minVol || undefined, min_age_hours: minAge || undefined, max_age_hours: maxAge || undefined, refresh })
      .then((d) => { setData(d); setErr(""); })
      .catch((e) => setErr(String(e)))
      .finally(() => setBusy(false));
  };

  useEffect(() => {
    load();
    cryptoApi.upcoming().then((d) => { setUpcoming(d.rows); setUpWhy(d.why ?? ""); }).catch((e) => setUpWhy(String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const rows = [...(data?.rows ?? [])].sort((a, b) => {
    const x = a[sort], y = b[sort];
    const c = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y));
    return asc ? c : -c;
  });
  const click = (k: SortKey) => { if (k === sort) setAsc(!asc); else { setSort(k); setAsc(k === "base" || k === "age_hours"); } };

  const filters = [
    minVol ? `volume ≥ ${vol(minVol)}` : "", minAge ? `age ≥ ${minAge}h` : "", maxAge ? `age ≤ ${maxAge}h` : "",
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
            <label className="flex flex-col text-theme-xs text-gray-500 dark:text-gray-400">min age h
              <input type="number" className={input} value={minAge || ""} onChange={(e) => setMinAge(Number(e.target.value))} /></label>
            <label className="flex flex-col text-theme-xs text-gray-500 dark:text-gray-400">max age h
              <input type="number" className={input} value={maxAge || ""} onChange={(e) => setMaxAge(Number(e.target.value))} /></label>
            <Button size="sm" disabled={busy} onClick={() => load(false)}>APPLY</Button>
            <Button size="sm" variant="outline" disabled={busy} onClick={() => load(true)}>FRESH SWEEP</Button>
          </div>
        </div>
        {data && (
          <p className="px-5 pt-2 text-theme-xs">
            {data.stale
              ? <span className="text-warning-600">This sweep is STALE — a refresh failed, so these are the last numbers that could be read ({new Date(data.fetched_at * 1000).toLocaleString()}).</span>
              : <span className="text-gray-500 dark:text-gray-400">{data.from_cache ? "cached" : "fresh"} sweep from {new Date(data.fetched_at * 1000).toLocaleString()}</span>}
          </p>
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
                <TableRow key={c.symbol}>
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
                    {u.open_ms ? new Date(u.open_ms).toLocaleString() : "time not published"}
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
