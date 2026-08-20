---
name: verifying-ui-with-playwright
description: Use when changing anything the TradingAgents web UI renders (app.py, crypto_screener.py, webapp_announcements.py, CSS, layout, Streamlit widgets) and before reporting that change as done — also when the user reports a blank page, missing element, broken layout, or "nothing shows".
---

# Verifying UI with Playwright

## Overview

Passing tests, a clean compile, and HTTP 200 prove the server runs — not that the page is right. **Never report a UI change as done until you have loaded the real page, screenshotted it, and seen the change with your own eyes.** This is the user's #1 rule for this repo.

Baseline failure (why this skill exists): a change was reported "done" twice on tests + HTTP 200 alone; both times the live page was wrong (element in the wrong column, then a giant layout gap from vertical centering). A DOM probe + screenshot caught both immediately.

## The Loop

1. **Restart the server — by PID, never by name.**
   Since 2026-08-21 port 8503 serves the **React app** (Next.js), not
   Streamlit, with the Python API behind it on 8787. `./start.sh` frees both
   ports by PID, rebuilds, and waits for `/api/health` to answer:
   ```bash
   cd "/Users/jeremydevera/Desktop/Trading Agents" && ./start.sh
   # ./start.sh status  -> which ports are held, and whether the proxy answers
   # ./start.sh stop    -> free both ports by PID
   ```
   A UI-only change needs no restart in dev (`cd webapp && npm run dev`, port
   3000, same `/api` proxy). `pkill -f` anything is still forbidden.

   **The API is same-origin.** The browser calls `/api/...` on 8503 and Next
   rewrites it to 8787, so a screen that renders but shows no numbers means
   the API process died — check `./start.sh status` before blaming the page.
2. **Run the verify script** (bootstraps its own Playwright on first use):
   ```bash
   cd .claude/skills/verifying-ui-with-playwright/scripts && ./verify.sh "http://localhost:8503/trade" "Open positions"
   ```
   It screenshots the page and prints the bounding box of every element whose
   text you pass with `--find "Some text"` (repeatable).
3. **Read the screenshot with the Read tool.** Look at it. Is the change where the user asked? Is anything else now broken (gaps, overlaps, below-the-fold surprises)?
4. **Check geometry, not just presence.** An element can exist and still be in the wrong column. Compare x/y of the changed element against its intended neighbours.
5. Only after 3–4 pass: report done, stating what the screenshot shows.

## Red Flags — STOP, you are about to violate the rule

- "Tests pass, so it works"
- "HTTP 200, page serves fine"
- "The edit is trivial, no need to look"
- "The element is in the DOM" (position unchecked)
- "I'll let the user check in their browser"
- Reaching for `pkill -f streamlit`

**All of these mean: run the loop above before saying anything is done.**

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Screenshot taken before Streamlit finishes rendering | Script waits ~8s after networkidle; extend `--wait` for slow fetches |
| Element found but below the fold | Check the y coordinate against viewport height (1050) |
| Styling a Streamlit testid that no longer exists (silently dead CSS) | Probe the live DOM for the testid first (`--dump-testids`) |
| Verifying only the changed screen | Click through both tabs when CSS is app-wide |
| `button:text-is("X")` never matches — Streamlit nests button text in a markdown `<p>` | Streamlit-era note. In React use `locator('button', { hasText: /^X$/ })` |
| Asserting a LIVE figure (unrealized PnL, wallet) equals a later API read | It moved between render and assert. Assert DOM-internal consistency instead — itemised rows must SUM to the total tile — plus a tolerance against a fresh sample |
| A `confirm()` dialog blocks the run and the click looks dead | `page.on('dialog', d => d.dismiss())` before clicking anything that saves or stops |
| Reading a shape you did not check (`daily_pnl` returns objects, not floats) | One `v.toFixed is not a function` blanks the WHOLE page and every assert fails at once. Read the emitter (CLAUDE.md 23) — then `page.on('pageerror')` catches what is left |
| `getByRole('button', {name:'Close'})` matches the dialog's X icon (aria-label "Close") — false "run finished" at t+5s | Scope to `[data-testid="stButton"]` for the real text button |
| Clicking anything while an analysis streams restarts it from stage 0 | Wait for the stButton "Close" (renders only after the outcome is stored) before any click |
| `getByLabel('My field')` resolves to the **help tooltip button** when the widget was given `help=...` — Streamlit gives it `aria-label="Help for My field"`, and `fill()` then dies with "Element is not an `<input>`" | Target the widget container: `locator('[data-testid="stNumberInput"]').filter({hasText:'My field'}).locator('input')` |
| A regex against `innerText` misses a heading styled `text-transform: uppercase` — Chromium's `innerText` returns the *rendered* case, so a `<h4>Losing trades</h4>` reads as `LOSING TRADES` | Match case-insensitively (`/losing trades/i`) — and when a check fails, read the screenshot before assuming the UI is broken |

## Presence is not correctness

Every check in this skill confirms an element EXISTS and sits where it should. That
passes on a tile whose number is right and whose label is a lie — which is how
`+ open (RUNE) +7.59` shipped while RUNE was `+0.16` and the figure summed four
positions.

So add one more assertion to any check involving a figure: **recompute the value from
its source and compare it to the rendered text**, and for any itemised list, **assert
the items sum to the displayed total**. See `label-must-match-data`.
