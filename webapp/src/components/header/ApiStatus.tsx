"use client";
/** Live probe of the FastAPI backend. The chip is derived from the actual
 * response — green only after /api/health answered ok on this poll. */
import { useEffect, useState } from "react";
import { api, API_BASE } from "@/lib/api";

export default function ApiStatus() {
  const [state, setState] = useState<"checking" | "up" | "down">("checking");

  useEffect(() => {
    let alive = true;
    // TWO consecutive failures before saying "unreachable". One slow answer is
    // not an outage: while a 3,960-pair sweep has the machine, a probe can
    // exceed the timeout and come straight back on the next poll. Claiming the
    // API is down when it is merely busy is a false label on a live system.
    let misses = 0;
    const probe = () =>
      api.health()
        .then((h) => { if (!alive) return; misses = 0; setState(h.ok ? "up" : "down"); })
        .catch(() => {
          if (!alive) return;
          misses += 1;
          if (misses >= 2) setState("down");
        });
    probe();
    const t = setInterval(probe, 10000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  return (
    <span className="inline-flex h-11 items-center gap-2 rounded-lg border border-gray-200 px-4 text-theme-sm text-gray-600 dark:border-gray-800 dark:text-gray-300">
      <span className={`h-2 w-2 rounded-full ${
        state === "up" ? "bg-success-500" : state === "down" ? "bg-error-500" : "bg-warning-400"
      }`} />
      {state === "up" ? (API_BASE ? `API on ${API_BASE.replace("http://", "")}` : "API connected")
        : state === "down" ? `API unreachable${API_BASE ? ` at ${API_BASE}` : ""}`
        : "checking API…"}
    </span>
  );
}
