# My skills

The custom skills in this repo, in plain words. Type `/name` in Claude to use
one. They live in `.claude/skills/`. **When a new skill is made, add a row
here** — this file exists because the operator won't remember them all
(2026-09-05).

## Always on (run by themselves, no need to type)

| skill | what it does |
|---|---|
| `short-and-plain` | Every answer short, in basic words, and **always with a real example** from your own data. A fact = 1 sentence. |
| `bug-scenario` | A bug is always shown as a step-by-step story with real times and dollars, never just code talk. |
| `say-done` | Speaks one sentence out loud when a task finishes. Edit its voice in `.claude/skills/say-done/config.json`. |
| `three-gates` | Before any answer or "done": is it measured, is it real, was it tested. |
| `label-must-match-data` | Every label on screen must match the number under it. Runs before reporting any UI change. |
| `verify-ui-change` | Any change to how the app looks gets checked with a real browser screenshot before saying done. |
| `harddev` | Every code change: build → loop "is there a potential bug?" until none → only then test. Made 2026-09-05. |
| `blast-radius` | After any code change: check what else that change touches. |
| `store-strategy` | Any new strategy is only finished when **you can find it in Stored strategies by its #id** — measuring writes files, the panel reads the index, and nothing joins the two by itself. Made 2026-09-12, after 6,845,648 new rows were measured and the panel showed none of them. |
| `rca-log` | Every bug that gets fixed is written into `docs/RCA.md` in the same commit — what you saw, the timeline, the cause, **why the test missed it**, the cost, and the test that now stops it. Made 2026-09-09. |
| `workflow-map` | Ask "how does it work" or "give me the workflow" and the answer is the **boxed arrow diagram** — numbered stages, a branch box at every decision, a loop in a double box, and a "if anything fails" block at the bottom. One line of plain words under it, never a paragraph above it. Made 2026-09-10. |
| `press-and-watch` | Any of the long jobs — DOWNLOAD CANDLES, UPDATE CANDLES, RESOLVE PENDING, BACKTEST, UPDATE ALL BACKTEST — is watched to the END, not for ten seconds. Guess what will break first, press it the way the button does, fix with `harddev`, press again. Made 2026-09-05.  Use '/goal' dont stop until all is pending is resolved loop until you resolve all, if you have question then ask your self what is best approach that wont cause any bug then report me what changed.


## Trading (type these when you want them)

| skill | what it does |
|---|---|
| `/full-grid-search` | Any "find me a strategy" ask runs the FULL grid: all coins × 5 timeframes × all signals × TP/SL pairs × flat and martingale. |
| `/still-working` | Checks a strategy is making money NOW (last 1/3/6 months), not just over its whole history. Run before deploying anything. |
| `/analyze15m30m` | Best win rate for a coin on 15m + 30m over a full year that still makes money → artifact. |
| `/analyze1hr4hr` | Same, for 1h + 4h. |
| `/yearly-strategy-sweep` | Re-runs the whole-market sweep ("what's working now"). |
| `/store-indexes` | Fixes the Stored-strategies page when it is slow or missing rows after a big sweep. |
| `/feedcheck` | Trade report since the LAST feedcheck (opened, won, lost and why, refused and why, EMERGENCY list), then judges the feed lines: normal or bug. |

## Building and checking the app

| skill | what it does |
|---|---|
| `/strict` | Forces browser-screenshot proof of UI work before "done". |
| `/verifying-ui-with-playwright` | The how-to for checking the web UI with a real browser. |
| `/ui-ux-pro-max` | Design help: styles, colors, fonts, layout rules, with a search tool. |
| `/web-design-guidelines` | Reviews UI code against accessibility and interface rules. |
| `/pick-ui-library` | Picks the right frontend library for a job (dates, toasts, charts...). |
| `/prototype` | Builds several different versions of a UI piece to pick from. |

## Design pack (imported set, used less often)

`animate`, `animation-vocabulary`, `apple-design`, `ask-sonner`,
`banner-design`, `brand`, `design`, `design-system`, `emil-design-eng`,
`extract-design-system`, `find-animation-opportunities`, `improve-animations`,
`review-animations`, `slides`, `ui-styling` — animation, branding, banner and
slide helpers. Open `.claude/skills/<name>/SKILL.md` for any of them.
