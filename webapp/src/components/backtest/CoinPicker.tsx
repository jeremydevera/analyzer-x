"use client";
/** Pick contracts from the exchange's own list — never by typing them.
 *
 * The operator's ask, twice: a real multi-select, and "show me total of coins
 * selected". Typing a symbol invites a typo that silently tests nothing, so
 * the list is the source and free text only FILTERS it.
 */
import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";

export default function CoinPicker({ value, onChange }: {
  value: string[]; onChange: (v: string[]) => void;
}) {
  const [all, setAll] = useState<string[]>([]);
  const [why, setWhy] = useState("");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);

  useEffect(() => {
    api.contracts().then((d) => { setAll(d.rows); setWhy(d.why); }).catch((e) => setWhy(String(e)));
  }, []);

  const shown = useMemo(() => {
    const needle = q.trim().toUpperCase();
    const list = needle ? all.filter((s) => s.includes(needle)) : all;
    return list.slice(0, 300);
  }, [all, q]);

  const toggle = (s: string) =>
    onChange(value.includes(s) ? value.filter((x) => x !== s) : [...value, s]);

  return (
    <div className="relative">
      <div className="flex min-h-10 flex-wrap items-center gap-1 rounded-lg border border-gray-300 px-2 py-1.5 dark:border-gray-700">
        {value.map((s) => (
          <span key={s} className="flex items-center gap-1 rounded-full bg-brand-500 px-2 py-0.5 text-theme-xs text-white">
            {s.replace("_USDT", "")}
            <button onClick={() => toggle(s)} aria-label={`remove ${s}`} className="opacity-80 hover:opacity-100">×</button>
          </span>
        ))}
        <input
          value={q}
          onChange={(e) => { setQ(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          placeholder={value.length ? "add another…" : "search contracts…"}
          className="min-w-32 flex-1 bg-transparent text-theme-sm text-gray-700 outline-hidden placeholder:text-gray-400 dark:text-gray-300"
        />
        {value.length > 0 && (
          <button onClick={() => onChange([])}
            className="rounded-lg border border-gray-200 px-2 py-0.5 text-theme-xs text-gray-500 dark:border-gray-700 dark:text-gray-400">
            clear
          </button>
        )}
      </div>

      <p className="mt-1 text-theme-xs text-gray-500 dark:text-gray-400">
        {why
          ? <span className="text-warning-600">contract list unavailable — {why}</span>
          : value.length
            ? <><b>{value.length}</b> of {all.length.toLocaleString()} coins selected</>
            : <>none of {all.length.toLocaleString()} coins selected</>}
      </p>

      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute z-20 mt-1 max-h-72 w-full overflow-auto rounded-xl border border-gray-200 bg-white p-1 shadow-theme-lg dark:border-gray-700 dark:bg-gray-900">
            {shown.length === 0 && (
              <p className="px-3 py-2 text-theme-sm text-gray-500 dark:text-gray-400">
                {all.length ? `no contract matches “${q}”` : "loading the exchange's contract list…"}
              </p>
            )}
            {shown.map((s) => (
              <button key={s} onClick={() => toggle(s)}
                className={`flex w-full items-center justify-between rounded-lg px-3 py-1.5 text-left text-theme-sm hover:bg-gray-50 dark:hover:bg-white/[0.05] ${
                  value.includes(s) ? "text-brand-600 dark:text-brand-400" : "text-gray-700 dark:text-gray-300"}`}>
                {s.replace("_USDT", "")}
                <span className="text-theme-xs text-gray-400">{value.includes(s) ? "selected" : s}</span>
              </button>
            ))}
            {all.length > shown.length && (
              <p className="px-3 py-1.5 text-theme-xs text-gray-400">
                showing {shown.length} of {all.length.toLocaleString()} — type to narrow
              </p>
            )}
          </div>
        </>
      )}
    </div>
  );
}
