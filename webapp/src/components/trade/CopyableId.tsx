"use client";
/** THE ONE COPYABLE ID IN THIS APP.

 *  Lifted out of StrategiesGrid on Sep 10, 2026, when the operator said of
 *  the positions table *"i still cannot copy the id ... y5ubbfpb"*: the grid
 *  had this — an icon so the id LOOKS copyable, and a hidden-textarea
 *  fallback for a browser that refuses the async clipboard — while the
 *  positions table had a hand-rolled button with neither. One component now,
 *  so the next table cannot be born broken.
 *
 *  `prefix` is what the reader sees before the id ("trade "), and `value`
 *  overrides what lands on the clipboard when they differ.
 */
import { useState } from "react";

export default function CopyableId(
  { id, prefix = "#", value, dim = false }:
  { id: string; prefix?: string; value?: string; dim?: boolean },
) {
  const [state, setState] = useState<"" | "ok" | "fail">("");

  const copy = async () => {
    const text = value ?? `${prefix}${id}`;
    let ok = false;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        ok = true;
      }
    } catch { ok = false; }
    if (!ok) {
      // no async clipboard (or it refused): the old selection route
      try {
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.setAttribute("readonly", "");
        ta.style.position = "fixed";
        ta.style.top = "-1000px";
        document.body.appendChild(ta);
        ta.select();
        ok = document.execCommand("copy");
        ta.remove();
      } catch { ok = false; }
    }
    setState(ok ? "ok" : "fail");
    window.setTimeout(() => setState(""), 1500);
  };

  return (
    <span className="flex items-center gap-1">
      <button onClick={copy} title={`copy ${prefix}${id} to the clipboard`}
        className={`font-mono text-[11px] hover:underline ${dim ? "text-gray-500 dark:text-gray-400" : "font-semibold text-brand-500"}`}>
        {prefix}{id}
      </button>
      <button onClick={copy} aria-label={`copy ${prefix}${id}`}
        title={`copy ${prefix}${id} to the clipboard`}
        className="shrink-0 rounded p-0.5 text-gray-400 hover:bg-gray-100 hover:text-brand-500 dark:hover:bg-white/10">
        {state === "ok" ? (
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" strokeWidth="3" strokeLinecap="round"
               strokeLinejoin="round" className="text-success-600">
            <path d="M20 6 9 17l-5-5" />
          </svg>
        ) : state === "fail" ? (
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" strokeWidth="3" strokeLinecap="round"
               strokeLinejoin="round" className="text-error-500">
            <path d="M18 6 6 18M6 6l12 12" />
          </svg>
        ) : (
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" strokeWidth="2" strokeLinecap="round"
               strokeLinejoin="round">
            <rect x="9" y="9" width="11" height="11" rx="2" />
            <path d="M6 15H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v1" />
          </svg>
        )}
      </button>
      {state === "ok" && (
        <span role="status" className="text-[10px] font-medium text-success-600">
          copied
        </span>
      )}
      {state === "fail" && (
        <span role="status" className="text-[10px] font-medium text-error-500">
          could not copy — select it and press Ctrl+C
        </span>
      )}
    </span>
  );
}
