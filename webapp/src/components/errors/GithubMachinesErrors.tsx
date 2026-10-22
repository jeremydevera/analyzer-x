"use client";
/** GITHUB MACHINES — every red machine on both GitHub accounts, with its log
 *  saved on this PC (operator, Oct 19, 2026: "can you do a logging option
 *  where if there is error in github machines it will save the log in error
 *  tab"). Filtered and paged by the server (`/api/errors/github`,
 *  tradingagents/github_errors.py); the whole saved log opens from each
 *  machine's row. An empty list says what was looked at and when. */
import { useCallback, useState } from "react";
import { API_BASE, fmtWhen } from "@/lib/api";
import { useLiveRefresh } from "@/lib/live";
import PageButtons from "@/components/common/PageButtons";

type Job = { id: number; name: string; conclusion: string; started: number; ended: number;
  step: string | null; notes: string[]; log: string | null; log_bytes: number; log_cut: boolean;
  error: string; context: string; log_why: string };
type Run = { key: string; account: string; repo: string; run: number; workflow: string;
  title: string; conclusion: string; url: string; created: number; ended: number;
  machines: number; red: number; jobs: Job[] };
type Listing = { rows: Run[]; matched: number; total: number; page: number; pages: number;
  workflows: string[]; accounts: string[]; last_try: number | null; last_ok: number | null;
  last_error: string; since_days: number; every_s: number };

const WORDS: Record<string, string> = {
  failure: "failed", timed_out: "ran out of time", startup_failure: "could not start",
};

function size(n: number): string {
  return n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1000))} KB`;
}

export default function GithubMachinesErrors() {
  const [d, setD] = useState<Listing | null>(null);
  const [err, setErr] = useState("");
  const [account, setAccount] = useState("");
  const [workflow, setWorkflow] = useState("");
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<string>("");
  const load = useCallback(() => {
    const q = new URLSearchParams({ account, workflow, page: String(page) });
    fetch(`${API_BASE}/api/errors/github?${q}`, { cache: "no-store" })
      .then(async (r) => {
        if (!r.ok) throw new Error(`/api/errors/github -> HTTP ${r.status}`);
        return (await r.json()) as Listing;
      })
      .then((x) => { setD(x); setErr(""); })
      .catch((e) => setErr(String(e?.message ?? e)));
  }, [account, workflow, page]);
  useLiveRefresh(load, 60_000, [load]);

  const sel = "rounded-lg border border-gray-300 bg-transparent px-2 py-1 text-theme-xs dark:border-gray-700 dark:text-gray-300";
  const pick = (f: () => void) => { f(); setPage(1); };

  return (
    <div className="overflow-hidden rounded-2xl border border-gray-200 bg-white p-5 dark:border-white/[0.05] dark:bg-white/[0.03]">
      <h3 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">GitHub machines</h3>
      <p className="mt-1 text-theme-xs text-gray-500 dark:text-gray-400">
        Every machine that ended red on your GitHub accounts, with its log saved on this PC.
        A stopped (cancelled) run is not listed — it was stopped on purpose.
        {d && <> Checked every {Math.round(d.every_s / 60)} minutes; kept {d.since_days} days.
          {d.last_ok ? ` Last full look ${fmtWhen(d.last_ok)}.` : " Not looked yet."}</>}
      </p>
      {err && <p className="mt-3 text-theme-xs text-error-500">could not read the GitHub errors — {err}</p>}
      {d?.last_error && (
        <p className="mt-3 rounded-lg border border-warning-300 bg-warning-50 px-3 py-2 text-theme-xs text-warning-700 dark:border-warning-500/30 dark:bg-warning-500/10 dark:text-warning-400">
          The last look{d.last_try ? ` (${fmtWhen(d.last_try)})` : ""} could not read everything, so this list may be missing some: {d.last_error}
        </p>
      )}
      {!d && !err && <p className="mt-3 text-theme-xs text-gray-400">reading the saved GitHub errors…</p>}
      {d && (
        <>
          <div className="mt-4 flex flex-wrap items-center gap-2 text-theme-xs text-gray-500 dark:text-gray-400">
            <select aria-label="Account" className={sel} value={account} onChange={(e) => pick(() => setAccount(e.target.value))}>
              <option value="">{d.accounts.length === 2 ? "both accounts" : `all ${d.accounts.length} accounts`}</option>
              {d.accounts.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
            <select aria-label="Workflow" className={sel} value={workflow} onChange={(e) => pick(() => setWorkflow(e.target.value))}>
              <option value="">every job</option>
              {d.workflows.map((w) => <option key={w} value={w}>{w}</option>)}
            </select>
            {(account || workflow) && (
              <button type="button" className="text-brand-500" onClick={() => { setAccount(""); setWorkflow(""); setPage(1); }}>clear</button>
            )}
            <span className="ml-auto">
              {d.matched.toLocaleString()} red run{d.matched === 1 ? "" : "s"}
              {account || workflow ? ` of ${d.total.toLocaleString()}` : ""}
              {account ? ` · ${account}` : d.accounts.length === 2 ? " · both accounts" : ` · all ${d.accounts.length} accounts`}{workflow ? ` · ${workflow}` : ""}
            </span>
          </div>

          {d.rows.length === 0 ? (
            <p className="mt-4 text-theme-xs text-gray-500 dark:text-gray-400">
              {d.last_ok
                ? `No red machine on ${account || (d.accounts.length === 2 ? "either account" : `any of ${d.accounts.length} accounts`)}${workflow ? ` in ${workflow}` : ""} in the last ${d.since_days} days looked at.`
                : "The first look at GitHub has not run yet; it runs within 10 minutes of the site starting."}
            </p>
          ) : (
            <ul className="mt-3 flex flex-col gap-3">
              {d.rows.map((r) => (
                <li key={r.key} className="rounded-xl border border-gray-200 p-3 dark:border-white/[0.06]">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <p className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">
                      {r.workflow} <span className="font-normal text-error-500">· {WORDS[r.conclusion] ?? r.conclusion}</span>
                    </p>
                    <a href={r.url} target="_blank" rel="noreferrer" className="text-theme-xs text-brand-500 hover:underline">
                      {r.account} · run {r.run}
                    </a>
                  </div>
                  <p className="mt-0.5 text-theme-xs text-gray-500 dark:text-gray-400">
                    {fmtWhen(r.created)} to {fmtWhen(r.ended)} · {r.red} of {r.machines} machine{r.machines === 1 ? "" : "s"} red
                    {r.title ? ` · ${r.title}` : ""}
                  </p>
                  <div className="mt-2 flex flex-col gap-2">
                    {r.jobs.map((j) => {
                      const k = `${r.key}/${j.id}`;
                      return (
                        <div key={k} className="rounded-lg bg-gray-50 p-2 dark:bg-white/[0.03]">
                          <p className="text-theme-xs text-gray-700 dark:text-gray-300">
                            <span className="font-medium">{j.name}</span>
                            {j.step ? ` · stopped at "${j.step}"` : ""} · {WORDS[j.conclusion] ?? j.conclusion} {fmtWhen(j.ended)}
                          </p>
                          {j.error && <p className="mt-1 break-words text-theme-xs text-error-500">{j.error}</p>}
                          {j.notes.map((n, i) => (
                            <p key={i} className="mt-1 break-words text-[11px] text-gray-500 dark:text-gray-400">GitHub: {n}</p>
                          ))}
                          {j.log ? (
                            <div className="mt-1 flex flex-wrap gap-3 text-[11px]">
                              <button type="button" className="text-brand-500 hover:underline"
                                onClick={() => setOpen(open === k ? "" : k)} aria-expanded={open === k}>
                                {open === k ? "hide the last lines" : "show the last lines"}
                              </button>
                              <a className="text-brand-500 hover:underline" target="_blank" rel="noreferrer"
                                href={`${API_BASE}/api/errors/github/log?name=${encodeURIComponent(j.log)}`}>
                                open the whole saved log ({size(j.log_bytes)}{j.log_cut ? ", the end only" : ""})
                              </a>
                            </div>
                          ) : (
                            <p className="mt-1 text-[11px] text-gray-500 dark:text-gray-400">No log saved: {j.log_why}</p>
                          )}
                          {open === k && j.context && (
                            <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-words rounded bg-gray-900 p-2 text-[11px] leading-snug text-gray-100">{j.context}</pre>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </li>
              ))}
            </ul>
          )}
          <PageButtons cur={d.page} pages={d.pages} goto={setPage} what="GitHub errors" />
        </>
      )}
    </div>
  );
}
