"use client";
/** Live probe of the FastAPI backend. The chip is derived from the actual
 * response — green only after /api/health answered ok on this poll. */
import { useEffect, useState } from "react";
import { api, API_BASE } from "@/lib/api";

export default function ApiStatus() {
  const [state, setState] = useState<"checking" | "up" | "down">("checking");

  useEffect(() => {
    let alive = true;
    const probe = () =>
      api.health()
        .then((h) => alive && setState(h.ok ? "up" : "down"))
        .catch(() => alive && setState("down"));
    probe();
    const t = setInterval(probe, 10000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  return (
    <span className="inline-flex h-11 items-center gap-2 rounded-lg border border-gray-200 px-4 text-theme-sm text-gray-600 dark:border-gray-800 dark:text-gray-300">
      <span className={`h-2 w-2 rounded-full ${
        state === "up" ? "bg-success-500" : state === "down" ? "bg-error-500" : "bg-warning-400"
      }`} />
      {state === "up" ? `API on ${API_BASE.replace("http://", "")}`
        : state === "down" ? `API unreachable at ${API_BASE}`
        : "checking API…"}
    </span>
  );
}
