"use client";
/** The bell. One place to see whether the thing you clicked actually worked.
 *
 * Downloads, backtests and every position opening or closing land here, from
 * a local SQLite feed (~/.tradingagents/notifications.db). A click that
 * reports nothing is indistinguishable from a click that failed silently —
 * which is how a 0-byte backtest report went unnoticed on 2026-08-20.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { NotifyRow, notifyApi } from "@/lib/api";

const POLL_MS = 20_000;

/** kind -> glyph + what the colour means. A loss is not a failure, so a
 *  closed trade takes its tone from the money, not from the run. */
const KIND: Record<string, { icon: string; label: string }> = {
  download: { icon: "↓", label: "download" },
  backtest: { icon: "⌗", label: "backtest" },
  trade_open: { icon: "→", label: "opened" },
  trade_close: { icon: "✓", label: "closed" },
  error: { icon: "!", label: "error" },
};

export default function NotificationDropdown() {
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState<NotifyRow[]>([]);
  const [unread, setUnread] = useState(0);
  const box = useRef<HTMLDivElement>(null);

  const load = useCallback(() => {
    notifyApi.list(30)
      .then((d) => { setRows(d.rows); setUnread(d.unread); })
      .catch(() => { /* the bell must never break the header */ });
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, POLL_MS);
    return () => clearInterval(t);
  }, [load]);

  // click-away close, so the panel does not sit over the page
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);

  const markAll = () => {
    notifyApi.markRead().then(() => { setUnread(0); load(); }).catch(() => {});
  };

  return (
    <div className="relative" ref={box}>
      <button
        onClick={() => { setOpen((v) => !v); if (!open) load(); }}
        aria-label={`notifications${unread ? `, ${unread} unread` : ""}`}
        aria-expanded={open}
        className="relative flex h-11 w-11 items-center justify-center rounded-full border border-gray-200 text-gray-500 transition hover:bg-gray-100 hover:text-gray-700 dark:border-gray-800 dark:text-gray-400 dark:hover:bg-white/[0.06] dark:hover:text-white"
      >
        {/* bell */}
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
          <path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.7 21a2 2 0 0 1-3.4 0" />
        </svg>
        {unread > 0 && (
          // the COUNT, not just a dot: "something happened" is less useful
          // than "three things happened"
          <span className="absolute -right-0.5 -top-0.5 flex min-w-[18px] items-center justify-center rounded-full bg-error-500 px-1 text-[10px] font-bold leading-[18px] text-white">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 z-50 mt-2 flex max-h-[26rem] w-[22rem] flex-col overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-theme-lg dark:border-gray-800 dark:bg-gray-900">
          <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3 dark:border-gray-800">
            <h5 className="text-sm font-semibold text-gray-800 dark:text-white/90">
              Activity
            </h5>
            {unread > 0 && (
              <button onClick={markAll}
                className="text-theme-xs font-medium text-brand-500 hover:underline">
                mark all read
              </button>
            )}
          </div>

          <ul className="flex-1 overflow-y-auto">
            {rows.map((r) => {
              const k = KIND[r.kind] ?? { icon: "•", label: r.kind };
              return (
                <li key={r.id}
                  className={`flex gap-3 border-b border-gray-50 px-4 py-3 last:border-0 dark:border-gray-800/60 ${
                    r.read ? "" : "bg-brand-50/40 dark:bg-brand-500/5"}`}>
                  <span className={`mt-0.5 flex h-6 w-6 flex-none items-center justify-center rounded-full text-[11px] font-bold ${
                    r.ok
                      ? "bg-success-50 text-success-600 dark:bg-success-500/15"
                      : "bg-error-50 text-error-600 dark:bg-error-500/15"}`}>
                    {k.icon}
                  </span>
                  <div className="min-w-0">
                    <p className="truncate text-theme-sm font-medium text-gray-800 dark:text-white/90">
                      {r.title}
                    </p>
                    {r.detail && (
                      <p className="mt-0.5 break-words text-theme-xs text-gray-500 dark:text-gray-400">
                        {r.detail}
                      </p>
                    )}
                    {/* a failed download made whole since says so — measured against
                        the store, so it never reads as live once the files exist */}
                    {r.resolved_why && (
                      <p className={`mt-0.5 break-words text-theme-xs ${
                        r.resolved ? "text-success-600 dark:text-success-400" : "text-error-500"}`}>
                        {r.resolved_why}
                      </p>
                    )}
                    <p className="mt-1 text-[10px] uppercase tracking-wide text-gray-400 dark:text-gray-500">
                      {k.label} · <span className="normal-case">{r.when}</span>
                      {!r.ok && (r.resolved
                        ? <span className="ml-1 font-semibold text-success-600 dark:text-success-400">· FAILED, SINCE RESOLVED</span>
                        : <span className="ml-1 font-semibold text-error-500">· FAILED</span>)}
                    </p>
                  </div>
                </li>
              );
            })}
            {!rows.length && (
              <li className="px-4 py-8 text-center text-theme-sm text-gray-500 dark:text-gray-400">
                Nothing yet. Downloads, backtests and trades land here.
              </li>
            )}
          </ul>
        </div>
      )}
    </div>
  );
}
