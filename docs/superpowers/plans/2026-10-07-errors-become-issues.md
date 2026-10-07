# Errors become GitHub issues, and a fixer checks each one — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** every error the system meets is filed once as a GitHub issue on
`jeremydevera/analyzer-x`, and a detached Claude run on this PC investigates
each one, posts a verdict, and fixes, pushes and restarts the back end when
it is a real fault.

**Architecture:** a filer (`tradingagents/error_issues.py`) gathers events
from the rooms' logs (`room_errors`), failed jobs (`db_jobs`) and the site's
own log, groups them by fingerprint, scrubs secrets and files/updates issues
through `gh`; a fixer launcher (`tradingagents/error_fixer.py`) runs one
`claude -p` at a time on a LOCAL evidence file and turns its result file into
the issue's verdict; `python start.py api` restarts only the back end and the
room runners. One API thread ticks filer and fixer every 120 s.

**Tech Stack:** Python 3.13 (stdlib, sqlite via existing modules), `gh` CLI,
Claude Code CLI 2.1.281 (`claude.exe -p`), FastAPI route, Next.js panel.

**Spec:** `docs/superpowers/specs/2026-10-07-errors-become-issues-design.md`

## Global Constraints

- Issues go to `jeremydevera/analyzer-x` only (public; the fork has issues off).
- Secrets never leave the PC: `MEXC_API_KEY`, `MEXC_API_SECRET`, the
  `~/.tradingagents/ingest_token` value, and any `signature=`, `ApiKey`,
  `Authorization`, `token`/`secret`/`key` value → `[removed]`.
- The fixer reads only `~/.tradingagents/fixer/<fp>.json`, never issue text.
- One fixer run at a time, at most 8 a day, 90 minutes each.
- The only restart a fixer may do is `python start.py api` (port 8503 untouched).
- Every printed date via `positions_view.fmt_when`; nothing below a
  `__main__` guard; commit through `scripts/commit_own.py`, push both remotes.
- No GitHub call, no `claude` spawn, from the job-supervisor loop itself.

## Review Focus

1. A burst of 500 distinct errors (a broken release) — one flood issue, never 500.
2. `gh` missing, signed out, or rate-limited — queued, retried, never raised.
3. An outsider's comment on a public issue — never read by the fixer.
4. The fixer's own restart — it must survive killing the API it was spawned from.
5. The same fault coming back after "fixed" — reopened once, then `needs-you`.

---

### Task 1: events, fingerprints and the scrubber

**Files:** Create `tradingagents/error_issues.py`; Test `tests/test_errors_become_issues.py`

**Interfaces — Produces:** `Event` (dict: `source, kind, label, message,
key, rooms, count, first, last, samples`), `fingerprint(ev) -> str`,
`scrub(text) -> str`, `collect(now) -> list[dict]` merging
`from_rooms()`, `from_jobs()`, `from_site_log()`.

- [ ] Write failing tests: a `room_errors.report` stub with the SUPRA group
  in two rooms → ONE event with both rooms; a failed `db_jobs.status` (`errors:
  2, first_error: "X"`) → one `job` event; an api.log traceback → one `site`
  event whose message is the last traceback line plus the deepest
  `tradingagents` frame; `fingerprint` ignores the room and the numbers;
  `scrub` removes each secret form (env key, env secret, token file value,
  `signature=abc`, `ApiKey: x`, `Authorization: Bearer y`).
- [ ] Run → FAIL (module missing).
- [ ] Implement with `room_errors._norm` for the key; `report(hours=0, page=n)`
  over every page; jobs from `db_jobs.FILES` / `status()`; the site log read as
  a byte-offset tail.
- [ ] Run → PASS. Commit.

### Task 2: the filer's GitHub side

**Files:** Modify `tradingagents/error_issues.py`; Test `tests/test_errors_become_issues.py`

**Interfaces — Produces:** `STATE` path, `tick(now, gh=None) -> dict`,
`GH_REPO = "jeremydevera/analyzer-x"`, `_gh(args) -> str` (raises
`GhFailed`), `issue_for(fp) -> dict | None` for the route.

- [ ] Failing tests with a fake `gh` recording calls, on one timeline: the
  first tick records a BASELINE (no issue for groups last seen before it); a
  new group files one issue with labels `auto-error`; a repeat within the hour
  posts nothing, after an hour one comment; a fixed fingerprint that recurs is
  reopened with `came-back` and queued, the second recurrence is `needs-you`;
  a `not_a_fault` one gets one comment a day; the 11th new issue in an hour
  becomes one `error flood` issue; a `gh` failure leaves the event queued and
  `tick` returns without raising; the bell is rung per new issue.
- [ ] Run → FAIL. Implement. Run → PASS. Commit.

### Task 3: the fixer launcher

**Files:** Create `tradingagents/error_fixer.py`; Test `tests/test_the_fixer_checks_each_issue.py`

**Interfaces — Consumes:** `error_issues` state (`queued` fingerprints).
**Produces:** `tick(now, spawn=None) -> dict`, `PROMPT`, `result_path(fp)`,
`evidence_path(fp)`, `MAX_RUNS_PER_DAY = 8`, `RUN_LIMIT_S = 5400`.

- [ ] Failing tests: one run at a time (lock + pid); the 9th run of a day
  waits; a run past 90 minutes is stopped and its fingerprint `needs-you`;
  a finished run's result file moves the issue (`fixed` closes with the
  commit, `not_a_fault` closes with the reason, `needs_you` stays open); a run
  that ended without a result is `needs-you`; the prompt names
  `evidence_path(fp)` and says never to read the issue's text; the spawn uses
  `portable.DETACHED` and `--dangerously-skip-permissions`.
- [ ] Run → FAIL. Implement. Run → PASS. Commit.

### Task 4: `python start.py api`

**Files:** Modify `start.py`; Test `tests/test_start_api_only.py`

- [ ] Failing test: `cmd_api()` frees `API_PORT` with `tree=False`, never
  touches `UI_PORT`, spawns uvicorn with the same command as `cmd_start`,
  waits for health, then restarts each room whose runner is wanted.
- [ ] Run → FAIL. Implement. Run → PASS. Commit.

### Task 5: wiring, the route and the tab

**Files:** Modify `tradingagents/api.py` (a new `error-issues` thread beside
the watcher thread; `/api/errors/rooms` rows gain `issue`),
`webapp/src/lib/api.ts`, `webapp/src/components/errors/DeployedTabsErrors.tsx`;
Test `tests/test_errors_become_issues.py`

- [ ] Failing tests: the thread exists and calls `error_issues.tick` and
  `error_fixer.tick`, not the supervisor loop; the route adds `issue` by
  fingerprint; the panel prints the issue state from the payload.
- [ ] Run → FAIL. Implement. Build the UI. Run → PASS. Commit.

### Task 6: docs and go-live

- [ ] CLAUDE.md section "Every error becomes an issue (MANDATORY — Oct 07, 2026)".
- [ ] One back-end restart (`python start.py api`), told to the operator first.
- [ ] Watch the first ticks: the baseline written, the next real error filed,
  its fixer run started, its verdict posted.
