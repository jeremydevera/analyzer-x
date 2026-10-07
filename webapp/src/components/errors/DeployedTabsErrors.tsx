"use client";
/** DEPLOYED TABS — the errors of every trading room (Auto Trade's tabs).
 *
 * Operator, Oct 01, 2026: *"can you create a tab called 'Errors' then create a
 * section Named 'Deployed Tabs' there i should see errors"*, asked right after
 * *"can you check if there has been outage for the tabs"*.
 *
 * Every filter is sent to the SERVER (`/api/errors/rooms`), which groups and
 * pages: a room writes tens of thousands of safety refusals a day, and a
 * filter over a page the server already cut answers about the page, not the
 * logs (CLAUDE.md, "filter where the data is"). Safety refusals are COUNTED
 * per room and never listed among the errors — they are the runner saying no
 * on purpose. An empty list names what it EXAMINED.
 */
import { useCallback, useState } from "react";
import { api, ErrorIssue, fmtWhen, RoomErrors } from "@/lib/api";
import { useLiveRefresh } from "@/lib/live";

const WINDOWS: [number, string][] = [[1, "last hour"], [6, "last 6 hours"],
  [24, "last 24 hours"], [168, "last 7 days"], [0, "everything read"]];

// EVERY ERROR BECOMES A GITHUB ISSUE (operator, Oct 07, 2026). The words come
// from the issue's state as the fixer left it — never a literal "fixed".
const ISSUE_WORDS: Record<string, string> = {
  queued: "filed, waiting to be checked",
  checking: "being checked",
  fixed: "fixed",
  not_a_fault: "not a fault",
  needs_you: "needs you",
  waiting: "not filed yet",
};

function issueWords(i: ErrorIssue): string {
  const words = ISSUE_WORDS[i.state] ?? i.state;
  return i.state === "fixed" && i.commit ? `${words} in ${i.commit.slice(0, 7)}` : words;
}

export default function DeployedTabsErrors() {
  const [d, setD] = useState<RoomErrors | null>(null);
  const [err, setErr] = useState("");
  const [room, setRoom] = useState("");
  const [kind, setKind] = useState("");
  const [hours, setHours] = useState(24);
  const [page, setPage] = useState(1);
  const load = useCallback(() => {
    api.roomErrors({ room, kind, hours, page })
      .then((r) => { setD(r); setErr(""); })
      .catch((e) => setErr(String(e?.message ?? e)));
  }, [room, kind, hours, page]);
  useLiveRefresh(load, 30_000, [load]);

  const windowName = WINDOWS.find(([h]) => h === hours)?.[1] ?? `last ${hours} hours`;
  const pick = (f: () => void) => { f(); setPage(1); };
  const sel = "rounded-lg border border-gray-300 bg-transparent px-2 py-1 text-theme-xs dark:border-gray-700 dark:text-gray-300";

  return (
    <div className="overflow-hidden rounded-2xl border border-gray-200 bg-white p-5 dark:border-white/[0.05] dark:bg-white/[0.03]">
      <h3 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">Deployed Tabs</h3>
      <p className="mt-1 text-theme-xs text-gray-500 dark:text-gray-400">
        What went wrong in each Auto Trade tab. Safety refusals (the runner saying no on
        purpose, such as fees too high for the target) are counted, not listed.
      </p>
      {err && <p className="mt-3 text-theme-xs text-error-500">could not read the errors — {err}</p>}
      {!d && !err && <p className="mt-3 text-theme-xs text-gray-400">reading every room&apos;s log…</p>}
      {d && (
        <>
          <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {d.rooms.map((r) => {
              const refusals = Object.entries(r.safety).reduce((a, [, n]) => a + n, 0);
              return (
                <button type="button" key={r.room} onClick={() => pick(() => setRoom(room === r.room ? "" : r.room))}
                  aria-pressed={room === r.room}
                  className={`rounded-xl border p-3 text-start ${room === r.room
                    ? "border-brand-500" : "border-gray-200 dark:border-gray-700"}`}>
                  <p className="flex items-center justify-between text-theme-sm font-semibold text-gray-800 dark:text-white/90">
                    {r.room === "main" ? "Main" : `#${r.room}`}
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${r.running
                      ? "bg-success-50 text-success-600 dark:bg-success-500/15" : "bg-error-50 text-error-600 dark:bg-error-500/15"}`}>
                      {r.running ? "running" : "NOT RUNNING"}
                    </span>
                  </p>
                  <p className={`mt-1 text-theme-xs ${r.errors ? "text-error-500" : "text-gray-500 dark:text-gray-400"}`}>
                    {r.errors ? `${r.errors.toLocaleString()} error${r.errors === 1 ? "" : "s"}` : "no errors"} · {windowName}
                    {r.last_error ? ` · last ${fmtWhen(r.last_error)}` : ""}
                  </p>
                  <p className="mt-1 text-[11px] text-gray-400">
                    {refusals
                      ? `${refusals.toLocaleString()} safety refusals: ` + Object.entries(r.safety)
                        .map(([k, n]) => `${n.toLocaleString()} ${d.safety_labels[k] ?? k}`).join(", ")
                      : "no safety refusals"}
                  </p>
                  <p className="mt-1 text-[11px] text-gray-400">
                    {r.examined.to ? `log read ${fmtWhen(r.examined.from ?? r.examined.to)} to ${fmtWhen(r.examined.to)}`
                      : "nothing logged yet — no strategy switched on"}
                  </p>
                </button>
              );
            })}
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-2 text-theme-xs text-gray-500 dark:text-gray-400">
            <select aria-label="Room" className={sel} value={room} onChange={(e) => pick(() => setRoom(e.target.value))}>
              <option value="">every tab</option>
              {d.rooms.map((r) => <option key={r.room} value={r.room}>{r.room === "main" ? "Main" : `#${r.room}`}</option>)}
            </select>
            <select aria-label="Kind" className={sel} value={kind} onChange={(e) => pick(() => setKind(e.target.value))}>
              <option value="">every kind</option>
              {d.kinds.map((k) => <option key={k.kind} value={k.kind}>{k.label}</option>)}
            </select>
            <select aria-label="Window" className={sel} value={hours} onChange={(e) => pick(() => setHours(Number(e.target.value)))}>
              {WINDOWS.map(([h, name]) => <option key={h} value={h}>{name}</option>)}
            </select>
            {(room || kind || hours !== 24) && (
              <button type="button" className="text-brand-500" onClick={() => { setRoom(""); setKind(""); setHours(24); setPage(1); }}>
                clear
              </button>
            )}
            <span className="ml-auto">
              {d.events.toLocaleString()} error{d.events === 1 ? "" : "s"} in {d.groups.toLocaleString()} group{d.groups === 1 ? "" : "s"}
              {" · "}{room ? (room === "main" ? "Main" : `#${room}`) : "every tab"}
              {kind ? ` · ${d.kinds.find((k) => k.kind === kind)?.label ?? kind}` : ""} · {windowName}
            </span>
          </div>

          {d.rows.length === 0 ? (
            <p className="mt-4 text-theme-xs text-gray-500 dark:text-gray-400">
              No errors in {d.rooms.length} tab{d.rooms.length === 1 ? "" : "s"} examined
              {" "}({windowName}{kind ? `, ${d.kinds.find((k) => k.kind === kind)?.label}` : ""}).
            </p>
          ) : (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full min-w-[720px] text-theme-xs">
                <thead>
                  <tr className="border-b border-gray-200 text-start text-gray-500 dark:border-gray-700 dark:text-gray-400">
                    <th className="px-2 py-1.5 text-start font-medium">Tab</th>
                    <th className="px-2 py-1.5 text-start font-medium">What</th>
                    <th className="px-2 py-1.5 text-end font-medium">Times</th>
                    <th className="px-2 py-1.5 text-start font-medium">First</th>
                    <th className="px-2 py-1.5 text-start font-medium">Last</th>
                    <th className="px-2 py-1.5 text-start font-medium">Latest message</th>
                    <th className="px-2 py-1.5 text-start font-medium">GitHub issue</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 dark:divide-white/[0.05]">
                  {d.rows.map((g) => (
                    <tr key={`${g.room}|${g.kind}|${g.first}|${g.message}`}>
                      <td className="px-2 py-1.5 whitespace-nowrap text-gray-700 dark:text-gray-300">{g.room === "main" ? "Main" : `#${g.room}`}</td>
                      <td className="px-2 py-1.5 whitespace-nowrap font-medium text-error-500">{g.label}</td>
                      <td className="px-2 py-1.5 text-end text-gray-700 dark:text-gray-300">{g.count.toLocaleString()}</td>
                      <td className="px-2 py-1.5 whitespace-nowrap text-gray-500">{fmtWhen(g.first)}</td>
                      <td className="px-2 py-1.5 whitespace-nowrap text-gray-500">{fmtWhen(g.last)}</td>
                      <td className="px-2 py-1.5 break-words text-gray-600 dark:text-gray-400">{g.message}</td>
                      <td className="px-2 py-1.5 whitespace-nowrap">
                        {g.issue ? (
                          <a href={g.issue.url} target="_blank" rel="noreferrer" className="text-brand-500 hover:underline">
                            #{g.issue.number} · {issueWords(g.issue)}
                          </a>
                        ) : (
                          <span className="text-gray-400">not filed</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {d.pages > 1 && (
            <div className="mt-3 flex items-center gap-2 text-theme-xs text-gray-500">
              <button type="button" disabled={d.page <= 1} onClick={() => setPage(d.page - 1)}
                className="rounded border px-2 py-0.5 disabled:opacity-40 dark:border-gray-700">‹ prev</button>
              <span>page {d.page} of {d.pages}</span>
              <button type="button" disabled={d.page >= d.pages} onClick={() => setPage(d.page + 1)}
                className="rounded border px-2 py-0.5 disabled:opacity-40 dark:border-gray-700">next ›</button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
