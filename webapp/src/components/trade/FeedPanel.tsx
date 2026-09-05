"use client";
/** The runner's own log, newest last — polled while the page is open. */
import { useEffect, useState } from "react";
import { tradeApi } from "@/lib/api";

export default function FeedPanel() {
  const [lines, setLines] = useState<string[]>([]);
  const [err, setErr] = useState("");

  useEffect(() => {
    const load = () => tradeApi.log(200).then((d) => { setLines(d.lines); setErr(""); }).catch((e) => setErr(String(e)));
    load();
    const t = setInterval(load, 8000);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="min-w-0 overflow-hidden rounded-2xl border border-gray-200 bg-white dark:border-white/[0.05] dark:bg-white/[0.03]">
      <h3 className="px-5 pt-4 text-base font-semibold text-gray-800 dark:text-white/90">Runner feed</h3>
      <p className="px-5 text-theme-xs text-gray-500 dark:text-gray-400">
        last {lines.length} lines from the runner&apos;s log on this PC
      </p>
      {err && <p className="px-5 pt-2 text-theme-sm text-error-500">{err}</p>}
      <pre className="m-4 max-h-80 overflow-auto rounded-xl bg-gray-50 p-3 text-theme-xs leading-relaxed text-gray-600 dark:bg-white/[0.03] dark:text-gray-300">
        {lines.length ? lines.join("\n") : "the runner has not written anything yet"}
      </pre>
    </div>
  );
}
