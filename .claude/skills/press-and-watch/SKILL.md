---
name: press-and-watch
description: Use whenever the operator asks to press one of the four long-running buttons — UPDATE CANDLES, DOWNLOAD CANDLES, BACKTEST, UPDATE ALL BACKTEST (and RESOLVE PENDING) — or asks to run the job behind one. ALSO use for WATCH MODE: when the operator asks to watch the UI in a browser for UI or backend errors, run scripts/watch_ui.mjs, then RCA and fix what it finds. Press it, predict what will break BEFORE it does, watch it for real until it finishes or fails, fix what breaks with the harddev loop, push, and press it again. Never report a button as working from its first ten seconds.
---

# Press and Watch

The operator, 2026-09-05:

> *"can you click the resolve 5055 pending, if there is an error then fix and
> push / i want to resolve the 5055 pending while at the same time i want you
> to detect if there will be a problem and do a fix for it then apply the
> harddev skill until its resolved"*

and: *"this skill applies to ff buttons: update candles button, download
candles, backtest, update all backtest"*.

## Why it exists

These four buttons start jobs that run for **minutes to days**, detached, on a
machine the operator is also using. Every failure this repo has paid for looked
fine for the first ten seconds:

* **Sep 05, 2:45pm** — the collect job downloaded twenty artifacts, parsed the
  first, then died on `TypeError: prog() takes from 1 to 3 positional arguments
  but 5 were given`. All the work done, nothing written. The first thirty
  seconds looked perfect.
* **Sep 03, 3:30pm** — the backtest restarted while memory was momentarily low,
  took 3 of 11 cores, and kept them for **28 hours**. Nothing was wrong at
  second ten.
* **Sep 02** — UPDATE BACKTEST reported `done: 860, rows: 0` with no note: 860
  pairs had raised `no Min15 candles for CETUS` because the spec used bare coin
  names. It looked like a run with nothing to do.
* **Aug 26, 5:20am** — a market-wide grid died with `MemoryError` after
  measuring 2,367 pairs perfectly. Hours of correct work, no report.

A button is not "working" because it started. It is working when it **finished
and the data landed**.

## The loop

### 1. PREDICT — before pressing

Write down, in one line each, what could go wrong THIS time. Not a recital —
look:

* **What does the job actually queue?** Read the spec it will build and count
  it. `RESOLVE 5,077 PENDING` that queues 5,173 pairs is a label disagreeing
  with its own run.
* **What is already running?** Two jobs writing the same store fight over pair
  locks. Check every job kind, not the one you are starting.
* **Is the machine able?** Free RAM against what the job needs per worker; free
  disk against what it writes; is it already paging.
* **Is this process on the current code?** `staleness.report()`. A job started
  before the fix cannot contain the fix.
* **Where does it write, and who else writes there?** A second Claude session
  is often in the same repo.
* **What happens on the failure path** — the venue raises, returns rubbish,
  returns slowly, or the runner is killed mid-write.

### 2. PRESS — the way the button does

Start it exactly as the UI would (`db_jobs.start(kind, spec)` with the spec the
component sends). Never hand-build a different spec: on 2026-09-02 a hand-built
spec used bare coin names and every pair failed, which the button would not
have done.

**`db_jobs.start()` returns the EXISTING pid when a job of that kind is already
alive.** A restart that returns the same pid started NOTHING — check the pid
changed before believing the job is new.

### 3. WATCH — until it finishes or fails

Not once. Not for ten seconds. Read the progress file, the job log and the
process itself, repeatedly, and specifically:

* is `done` advancing, or frozen while the process burns CPU?
* is the process alive at all, and using CPU, or spinning on nothing?
* is the row/pair count growing, or is it "starting" ten minutes in?
* did the count go BACKWARDS — that is a restart re-counting, not progress
* what does the log's last line say — read the emitter, not the label

### 3b. A QUESTION IS NOT A REASON TO STOP

Operator, 2026-09-05: *"if you have question then ask your self what is best
approach that wont cause any bug"*.

When something is unclear mid-run — which of two fixes, whether to restart,
whether a number is right — **do not stop and ask.** Ask yourself instead:
*what is the approach that cannot cause a bug?* Then take it.

The safe approach is almost always the one that:

* **measures instead of assuming** — read the emitter, count the thing, time it;
* **keeps the work already done** — checkpoint and resume rather than restart;
* **is reversible** — a new file beside the old one, never in-place;
* **fails loudly rather than quietly** — a named error beats a silent default;
* **does less** — fix the one thing, do not widen the change mid-run.

Only stop and ask when proceeding either way could **lose data or move real
money**. Everything else: pick the safe path, say which you picked and why in
the report, and keep going.

### 4. FIX — with the harddev loop

Any error, any freeze, any silent no-op: invoke **`harddev`** and follow it.
Dev, then hunt "is there a potential bug?" in rounds until the answer is no,
then test, then push. A bug found here gets a test so it stays fixed.

### 5. PRESS AGAIN

The fix is not proven by tests. Press the button again and watch it again.
Repeat 1-5 until the job finishes and the data is where it belongs.

### 6. REPORT WHAT CHANGED

Operator, 2026-09-05: *"then report me what changed after press and watch"*.

Not "it worked". A before-and-after, in numbers, plus what is different in the
code. Every report ends with:

| | |
|---|---|
| **Before** | the count when the button was pressed |
| **After** | the count now, measured, not assumed |
| **The run(s)** | pairs done, what was stored, errors, how many presses |
| **What broke** | each failure, its real timestamp, and whether it is fixed |
| **What changed in the code** | every file and why, or "nothing — it just worked" |
| **What is still not right** | named, or "nothing" |

Never "it works now" without the run that proves it. If the count did not move,
say so first — a run that finished cleanly and changed nothing is a bug, not a
success (2026-09-05: 3,101 pairs, 73,299 bars, zero errors, and the pending
count went UP).

## Rules

* **Never report a button as fixed from a passing test.** All four of these
  jobs have passed tests and then died in the field.
* **Finishing is not landing.** A cloud run at 100% whose rows are still in
  GitHub artifacts has not resolved anything. Follow the data to the store.
* **A failure is NAMED, never counted.** "3 failed" sends the reader to a log;
  name the pairs. That rule is in CLAUDE.md and these buttons are where it was
  bought.
* **Never restart the whole job for one bad item.** Delete that item's data,
  redo that item (`market_sweep.discard_pair`, `PAIR_RETRIES`).
* **Push every fix as it is made**, not at the end — anything CI runs from
  `main` is doubly urgent.
* **A `npm run build` under a running `next start` BREAKS the operator's
  screen.** `next start` serves the build it found when it launched, so
  rebuilding underneath it leaves the browser asking for chunk files that no
  longer exist — "Application error: a client-side exception has occurred
  while loading localhost", on every page. It happened on 2026-09-05: the
  server started 8:13:15pm, the rebuild landed 8:23:56pm, and the Candles page
  died. **Restart the web UI after every build**, and check a real page
  answers 200 with all its chunks present before saying the change is live.
* **Say what you left broken.** If something is another session's, or cannot be
  fixed from here, name it rather than letting it read as clean.

## WATCH MODE — the screen, like a person, on a loop (2026-09-15)

The operator: *"my goal is to watch the ui in browser and act like a human
looking for ui errors and backend errors once there are errors i need you to
collect those errors and do rca and document error then plan a solution and
deploy a fix"*.

Same loop as a button press, different trigger: instead of one job, the thing
being watched is **every screen**, and the thing that starts a cycle is a
finding rather than a click.

### How it runs

```bash
node .claude/skills/press-and-watch/scripts/watch_ui.mjs      --pages backtest,trade,candles,analysis,models,new-crypto      --settle 12000 --out findings.json
```

Exit **1** means it found something; **0** means the walk was clean. On a
`/loop`, that exit code is the whole trigger — quiet ticks cost nothing and say
nothing.

**It launches the Chrome already on this machine through `playwright-core`,
NOT the Playwright MCP server.** Two reasons, both measured here: the MCP
server times out connecting on this box (`CONNECT_TIMEOUT` after 30 s), and it
holds a single `mcp-chrome-*` profile that an orphaned browser locks with
"Browser is already in use" — a watchdog that needs a human to kill a Chrome
is not a watchdog. `scripts/package.json` pins `playwright-core` only, so
nothing downloads a browser.

### What counts as a finding

Only what a person would call wrong, because a watchdog that cries every tick
gets muted and then it is worth nothing:

| kind | what it means |
|---|---|
| `page-error` | an uncaught exception in the page |
| `console-error` | a console error, deduped across pages |
| `request-failed` / `http-4xx` / `http-5xx` | a call the screen made and did not get |
| `app-crash` | Next's "Application error: a client-side exception" screen |
| `blank-page` | rendered under 40 characters — the page is there and empty |
| `navigation-failed` | it would not load at all |
| `backend-error` | a traceback or `ERROR:`/`CRITICAL` written to `~/.tradingagents/*.log` **while the walk was running** |

Two deliberate choices, and do not "simplify" either:

* **The backend logs are read from the byte offset they held BEFORE the walk.**
  `api.log` is 25 MB of history; reporting last week's traceback as something
  this tick found is a false label, and the operator would stop reading the
  report by the third one.
* **The same error on six pages is ONE finding with six pages**, not six
  findings. A list nobody can read is the same as no list.

### Then the loop you already have

A finding is a bug report, so it enters the chain this repo already runs:

1. **REPRODUCE** — open that one page yourself and confirm it. A console error
   that fires once on a cold cache is not the same defect as one that fires
   every load.
2. **READ THE EMITTER** (CLAUDE.md rule 23) — open the code that wrote the
   line before explaining it. `http-503` from `/api/strategies` is a *missing
   sort index being built*, not an outage, and those want different fixes.
3. **`harddev`** — dev, then hunt "is there a potential bug?" in rounds until
   the answer is no, then test.
4. **`rca-log`** — `docs/RCA.md` entry in the SAME commit, CEO summary then DEV
   summary then the seven fields, and the fourth field (**why no test caught
   it**) is the one that stops the repeat.
5. **PUSH**, then **WALK AGAIN** and confirm the finding is gone. A fix is
   proven by the watchdog going quiet, never by a passing test.

### What this mode must never do

* **Never click a button that spends money or starts a long job.** Watch mode
  READS. It walks pages, it does not press BACKTEST, and it never touches
  anything on the Trade screen that could arm a strategy or place an order.
* **Never call the walk clean because the loop ran.** `walked` carries each
  page's character count for exactly this: `backtest(125049)` is a page that
  rendered, `backtest(0)` is one that did not, and both used to print the same
  "0 findings".
* **Never rebuild the UI under a running `next start`** — see the rule above;
  restart the UI after every build, or the next walk reports an app-crash you
  caused.

Measured on the first real run, Sep 15, 2026: `backtest` rendered 125,049
characters and `trade` 50,631, with **0 findings**. Pointed at a page that does
not exist it returned exit 1 with `http-404` and the matching `console-error` —
so the collector is known to bite, not assumed to.

## The four buttons, and what each really does

| Button | Job kind | Watch for |
|---|---|---|
| DOWNLOAD CANDLES | `download` | a cut connection mid-body, a delisted contract retried for ever, pairs lost and never named |
| UPDATE CANDLES | `download` (`mode: update`) | pairs the store never had being skipped; a stopped run leaving its tail untouched |
| RESOLVE PENDING | `download` (`mode: resolve`) | the queue matching the count on the button; delisted pairs attempted once, not counted as pending |
| BACKTEST | `backtest` | worker count pinned by a momentary memory dip; `done` re-counting from zero after a restart; MemoryError at the fold |
| UPDATE ALL BACKTEST | `btupdate` | an empty coin list meaning zero pairs; symbols vs bare coin names; the cloud half never being collected |

Whatever a run produces on GitHub must be **collected into the store**
(`cloud_autopilot` does this automatically; verify it did).
