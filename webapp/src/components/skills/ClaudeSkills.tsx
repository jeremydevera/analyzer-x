"use client";
/** CLAUDE SKILLS — every skill in this repo, grouped by what it is for.
 *
 * Operator, Oct 15, 2026: *"can you create a tab called 'Claude skills' then
 * categorize them for their function and what do they do / for example
 * harddev-categorize as coding then give me description"*.
 *
 * The list, the groups and every count come from the server
 * (`/api/claude-skills`, tradingagents/claude_skills.py), which reads the
 * skill folders on each call — nothing on this page is typed in by hand, so
 * a new skill appears here the day it is added.
 */
import { useEffect, useState } from "react";
import { API_BASE } from "@/lib/api";

type Skill = { name: string; group: string; description: string; always: boolean };
type Group = { name: string; about: string; skills: Skill[] };
type Listing = { total: number; always: number; groups: Group[] };

export default function ClaudeSkills() {
  const [d, setD] = useState<Listing | null>(null);
  const [err, setErr] = useState("");
  const [q, setQ] = useState("");

  useEffect(() => {
    fetch(`${API_BASE}/api/claude-skills`, { cache: "no-store" })
      .then(async (r) => {
        if (!r.ok) throw new Error(`/api/claude-skills -> HTTP ${r.status}`);
        return (await r.json()) as Listing;
      })
      .then((x) => { setD(x); setErr(""); })
      .catch((e) => setErr(String(e?.message ?? e)));
  }, []);

  // the whole list is one small answer (tens of skills), so searching it
  // here is searching all of it, never a page the server cut
  const needle = q.trim().toLowerCase();
  const shown = (d?.groups ?? []).map((g) => ({
    ...g,
    skills: g.skills.filter((s) => !needle
      || s.name.toLowerCase().includes(needle)
      || s.description.toLowerCase().includes(needle)
      || g.name.toLowerCase().includes(needle)),
  })).filter((g) => g.skills.length);
  const matched = shown.reduce((n, g) => n + g.skills.length, 0);

  return (
    <div className="overflow-hidden rounded-2xl border border-gray-200 bg-white p-5 dark:border-white/[0.05] dark:bg-white/[0.03]">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h3 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">Claude skills</h3>
          <p className="mt-1 text-theme-xs text-gray-500 dark:text-gray-400">
            The ways of working Claude follows in this app, grouped by what each one is for.
            {d && <> {d.total} skills in {d.groups.length} groups; {d.always} of them run by
              themselves, the rest only when the job calls for them.</>}
          </p>
        </div>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search skills"
          aria-label="Search skills"
          className="w-full rounded-lg border border-gray-300 bg-transparent px-3 py-1.5 text-theme-xs text-gray-800 sm:w-60 dark:border-gray-700 dark:text-gray-200"
        />
      </div>

      {err && <p className="mt-4 text-theme-xs text-error-600 dark:text-error-400">Could not read the skills: {err}</p>}
      {!d && !err && <p className="mt-4 text-theme-xs text-gray-500 dark:text-gray-400">Loading the skills...</p>}
      {d && needle && (
        <p className="mt-3 text-theme-xs text-gray-500 dark:text-gray-400">
          {matched} of {d.total} skills match &ldquo;{q.trim()}&rdquo;
          {" "}<button type="button" onClick={() => setQ("")}
            className="underline hover:text-gray-800 dark:hover:text-white/90">clear</button>
        </p>
      )}

      <div className="mt-4 flex flex-col gap-6">
        {shown.map((g) => (
          <section key={g.name}>
            <h4 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">
              {g.name} <span className="font-normal text-gray-500 dark:text-gray-400">({g.skills.length})</span>
            </h4>
            <p className="mt-0.5 text-theme-xs text-gray-500 dark:text-gray-400">{g.about}</p>
            <ul className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
              {g.skills.map((s) => (
                <li key={s.name}
                    className="rounded-xl border border-gray-200 p-3 dark:border-white/[0.06]">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <code className="break-all text-theme-xs font-semibold text-gray-800 dark:text-white/90">{s.name}</code>
                    <span className={
                      "rounded-full px-2 py-0.5 text-[11px] font-medium "
                      + (s.always
                        ? "bg-brand-50 text-brand-600 dark:bg-brand-500/15 dark:text-brand-400"
                        : "bg-gray-100 text-gray-600 dark:bg-white/[0.06] dark:text-gray-400")}>
                      {s.always ? "runs by itself" : "when needed"}
                    </span>
                  </div>
                  <p className="mt-2 text-theme-xs leading-relaxed text-gray-600 dark:text-gray-300">{s.description}</p>
                </li>
              ))}
            </ul>
          </section>
        ))}
        {d && !shown.length && (
          <p className="text-theme-xs text-gray-500 dark:text-gray-400">
            None of the {d.total} skills match &ldquo;{q.trim()}&rdquo;.
          </p>
        )}
      </div>
    </div>
  );
}
