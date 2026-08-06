---
name: strict
description: Use when the user types /strict — enforces visual verification of the web UI with Playwright before any change is reported as done.
---

# Strict

Alias for the full verification discipline.

**REQUIRED SUB-SKILL:** Invoke `verifying-ui-with-playwright` now and follow its loop exactly:

1. Restart streamlit **by PID only** (never `pkill` by name).
2. Run `.claude/skills/verifying-ui-with-playwright/scripts/verify.sh` with `--find` for every element the change touches.
3. Read the screenshot with the Read tool and look at it.
4. Check geometry (correct column, above the fold), not just presence.
5. Only then report — stating what the screenshot shows.

If there is no pending UI change, treat /strict as arming the rule for the rest of the session: every subsequent UI edit goes through the loop before being reported done. No exceptions — "tests pass", "HTTP 200", and "trivial edit" do not skip it.
