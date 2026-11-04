---
name: ai_stats
description: Use when the operator says "ai_stats" (or "/ai_stats", "ai stats", "top AI models", "best AI for coding/reasoning"). Shows the top 10 AI models for CODING and for REASONING from the Artificial Analysis free API, as two tables. Asked for Nov 04, 2026.
---

# ai_stats

The operator, Nov 04, 2026: *"okay use that api and create rule when i say
ai_stats showme top 10 ai models for coding and reasoning"*.

## Run it

```bash
.venv/Scripts/python .claude/skills/ai_stats/scripts/ai_stats.py          # top 10, kept 6 hours
.venv/Scripts/python .claude/skills/ai_stats/scripts/ai_stats.py --fresh  # ask the API again now
.venv/Scripts/python .claude/skills/ai_stats/scripts/ai_stats.py --top 20
```

Paste its two tables to the operator as printed, with the source line. Add
ONE plain sentence on top naming the #1 for coding and the #1 for reasoning,
with their scores. Nothing else.

## What it ranks

* **Coding**: Artificial Analysis's Coding Index, with LiveCodeBench and
  SciCode beside it.
* **Reasoning**: their Intelligence Index (their overall reasoning score),
  with GPQA (hard science questions) and Humanity's Last Exam beside it.
* A model with no score for a ranking is left out of that ranking, never
  ranked as 0.

## The key

The free API needs a key: an account at https://artificialanalysis.ai, then
an API key. It is kept on THIS PC only, never in the repo:
`~/.claude/ai_stats_key` (one line), or the environment variable
`ARTIFICIAL_ANALYSIS_API_KEY`. Without one the script prints the three steps -
pass them on as they are. Each PC needs its own copy of the file.

## Rules

* 1,000 asks a day are free; the answer is kept 6 hours in
  `~/.claude/cache/ai_stats.json`, so saying ai_stats often costs nothing.
* The API's terms require credit: always keep the
  "Source: Artificial Analysis (artificialanalysis.ai)" line.
* A refused key (401/403) or a used-up day (429) is said in plain words,
  never shown as an empty table.
