# Every error becomes a GitHub issue, and a fixer checks each one — design

Oct 07, 2026. The operator, after a manual pass over the Errors tab found 7
real faults among 34 error groups (the rest were 4 power cuts, a network-card
drop and deliberate restarts):

> *"here's what i want, everytime the system gets an error, file an issue to
> github, then i want you to investigate if its a valid error or not, if its
> valid then fix it"*

Their answers to the four questions that shaped it (Oct 07, 2026):

| question | answer |
|---|---|
| where the issues go | **Public project, as-is** — `jeremydevera/analyzer-x` (public; the `jeremydvera` fork has issues switched off) |
| where checking and fixing run | **On this PC** — it can read the rooms' records and logs |
| after a fix passes its tests | **Push and restart by itself** — back end and room programs only, the page stays up, a bell note says what changed |
| which errors | **All of them** — the Errors tab, failed jobs, crashes inside the site |

## What it does, in one picture

```
 error happens (room log / job / site)
          │
          ▼
 1. FILER (inside the site, its own thread, every 2 min)
    groups it by fingerprint, scrubs secrets, then on GitHub:
    new → open an issue · repeat → one comment an hour at most
          │
          ▼
 2. QUEUE (on this PC: ~/.tradingagents/error_issues.json)
          │  one at a time, at most 8 runs a day
          ▼
 3. FIXER (a detached `claude -p` run in G:\analyzer-x)
    reads the LOCAL evidence file (never the issue text),
    investigates the way the Oct 07 pass did, then writes a verdict:
      not a fault → comment why, close, label not-a-fault
      needs you   → comment why, leave open, ring the bell
      real fault  → failing test first, fix, related tests green,
                    docs/RCA.md entry, commit_own, push both accounts,
                    `python start.py api` + room runners restarted,
                    close with the commit, label fixed
          │
          ▼
 4. The Errors tab shows each group's issue and its state
```

## Units

### 1. `tradingagents/error_issues.py` — the filer

* **Sources (all three, the operator's "all of them"):**
  * `room_errors.report(hours=0)` — every group of every shown room, every
    page. Safety refusals stay excluded (they are counted, not errors).
  * failed jobs — each `db_jobs.FILES` kind whose `status()` is not running
    and reports a failure (`errors > 0` with `first_error`, a non-empty
    `failed` list, or the died-before-finishing note).
  * site crashes — `.run/api.log`, read as a tail like `room_errors._Tail`:
    a Python traceback's last line plus its deepest `tradingagents` frame,
    and `[supervisor] ... failed` / `could not` lines.
* **Fingerprint** = sha1 of (source, kind, normalised message) — the room is
  NOT part of it: the same fault in two rooms (SUPRA in #4FC03172 and
  #55D32617) is one issue listing both rooms.
* **One issue per fingerprint, never per occurrence.** A repeat adds one
  comment at most once an hour (new count, rooms, last seen). A fingerprint
  closed as *fixed* that comes back is reopened, labelled `came-back` and
  queued once more; the second time it comes back it is `needs-you` with a
  bell. A fingerprint closed as *not-a-fault* gets at most one comment a day
  and is not re-investigated.
* **Baseline:** groups whose last occurrence is before the filer first ran
  are recorded as seen and not filed — the 34 groups investigated by hand on
  Oct 07, 2026 are not re-filed. Anything that happens after is.
* **Flood guard:** at most 10 new issues an hour; past that, one summary
  issue (`error flood`) and a bell, the rest queued for the next hour.
* **Secrets are never posted**, whatever the "as-is" choice: the configured
  MEXC key and secret, the ingest token, and any `signature=`, `ApiKey`,
  `Authorization`, `token`/`secret` value are replaced by `[removed]`
  before anything leaves the PC. A test feeds a line carrying each one.
* **GitHub calls go through `gh`** (already signed in on this PC), never
  from the supervisor loop: the filer has its own thread. A failed call
  waits and retries next tick; it never raises into the site.
* **Labels:** `auto-error`, `checking`, `real-fault`, `not-a-fault`,
  `fixed`, `needs-you`, `came-back` — created once if missing.
* **Bell:** one `notifications.record("error_issue", ...)` per new issue and
  per verdict.

### 2. `tradingagents/error_fixer.py` — the fixer launcher

* **One run at a time**, a pid file plus an exclusive lock (a recycled pid
  is not proof of life, RCA-2026-09-12-B); **at most 8 runs a day**; a run
  is stopped after **90 minutes** and marked `needs-you` with its log tail.
* Launch: `claude.exe -p <prompt> --dangerously-skip-permissions
  --output-format stream-json` from `G:\analyzer-x`, detached
  (`portable.DETACHED`, like `start_runner`) so the API restart it performs
  cannot kill it; log in `~/.tradingagents/fixer/<issue>.log`.
* **The prompt names a LOCAL evidence file**
  (`~/.tradingagents/fixer/<fingerprint>.json`: the group, rooms, counts,
  first/last seen, sample lines). The issue on a public project can be
  commented on by anyone, so its text is never read as instructions — the
  issue number is used only to post the verdict.
* **The verdict is a file**, not prose: the run writes
  `~/.tradingagents/fixer/<fingerprint>.result.json`
  (`{"verdict": "fixed"|"not_a_fault"|"needs_you", "commit", "summary"}`),
  and the filer moves the issue from it. A run that ends without one is
  `needs-you`.
* **What a run may never do**, in the prompt and checked after the run where
  it can be: touch settings, keys, watcher rules or room configs; place or
  cancel orders; touch a real-money book; run `start.py start` (the full
  restart that darkens the page); force-push; delete data; edit a file that
  holds someone else's uncommitted change (it says `needs-you` instead).
* **Every rule of `CLAUDE.md` applies** — the run is a Claude Code session in
  the repo, so it loads it: test first, RCA entry in the same commit,
  `scripts/commit_own.py`, push to `origin` and `colleague`, dates via
  `fmt_when`, plain words in the comment it posts.

### 3. `python start.py api` — restart the back end only

`free_port(API_PORT, tree=False)`, spawn uvicorn exactly as `cmd_start` does,
wait for `/api/health`, then restart each room whose runner the operator
wants (`stop_runner` / `start_runner` under `profiles.using`). The page (port
8503) is never touched. A bell note before and after. This is the only
restart a fixer run may perform.

### 4. The Errors tab

`GET /api/errors/rooms` adds `issue: {number, url, state}` to each group by
fingerprint; `DeployedTabsErrors.tsx` shows it beside the group ("issue #123 ·
being checked", "fixed in 8bab83d", "not a fault", "needs you"). The label is
read from the state file, never a literal.

## Failure handling

| what fails | what happens |
|---|---|
| GitHub unreachable or `gh` refuses | the event stays queued; next tick retries; the tab says "not filed yet" |
| a fixer run crashes or times out | `needs-you`, its log tail in the issue comment, bell |
| the fix's tests are not green | no commit, no push; `needs-you` with the failing output |
| the same fault comes back after its fix | reopened once; the second time `needs-you` |
| the PC is off | nothing runs; on start the filer catches up from the logs |
| 11+ new faults in an hour | one flood issue, the rest wait an hour |

## Testing

* Filer, on one timeline with fake `gh`: a new group files once; a repeat
  comments once an hour; two rooms one issue; baseline groups are not filed;
  the flood guard; a failed `gh` call is retried, never raised; every secret
  pattern is removed.
* Sources: a room error, a failed job and an api.log traceback each become
  an event with the right fingerprint.
* Fixer: one run at a time; the daily cap; the 90-minute stop; a run with no
  result file is `needs-you`; the prompt names the local evidence file and
  never the issue body; the detached spawn uses `portable.DETACHED`.
* `start.py api`: frees only the API port (`tree=False`) and never the UI port.
* The tab: the issue badge's words come from the state file.

## Out of this cut

Checking errors when the site itself is down (nothing is running to file
them); investigating issues opened by anyone else; a fixer for the GitHub
fork (`jeremydvera` has issues switched off).
