"""ai_stats - the top AI models for coding and for reasoning, from the
Artificial Analysis free API (operator, Nov 04, 2026: "use that api and create
rule when i say ai_stats showme top 10 ai models for coding and reasoning").

    .venv/Scripts/python .claude/skills/ai_stats/scripts/ai_stats.py [--top N] [--fresh]

* The key is NEVER in the repo: the environment variable
  ARTIFICIAL_ANALYSIS_API_KEY, else the file ~/.claude/ai_stats_key (one line).
* The free API allows 1,000 requests a day, so an answer is kept for 6 hours
  in ~/.claude/cache/ai_stats.json (--fresh asks again).
* Coding is ranked by `artificial_analysis_coding_index`; reasoning by
  `artificial_analysis_intelligence_index` (their overall reasoning score), with
  GPQA and Humanity's Last Exam printed beside it. A model with no score for a
  ranking is left out of THAT ranking, never ranked as 0.
* Attribution is required by the API's terms: every printout names
  artificialanalysis.ai.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

URL = "https://artificialanalysis.ai/api/v2/data/llms/models"
KEY_ENV = "ARTIFICIAL_ANALYSIS_API_KEY"
KEY_FILE = Path.home() / ".claude" / "ai_stats_key"
CACHE = Path.home() / ".claude" / "cache" / "ai_stats.json"
CACHE_S = 6 * 3600
CREDIT = "Source: Artificial Analysis (artificialanalysis.ai), free API."

NO_KEY = (
    "No Artificial Analysis key on this PC yet.\n"
    "1. Make a free account at https://artificialanalysis.ai and create an API key.\n"
    f"2. Save the key as the only line of {KEY_FILE}\n"
    f"   (or set the environment variable {KEY_ENV}).\n"
    "3. Say ai_stats again."
)


def key() -> str | None:
    k = os.environ.get(KEY_ENV, "").strip()
    if k:
        return k
    try:
        k = KEY_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return k or None


def fetch(api_key: str, fresh: bool = False, now: float | None = None) -> tuple[list[dict], float]:
    """The models list and when it was read (seconds), from the cache while it
    is under CACHE_S old."""
    now = time.time() if now is None else now
    if not fresh:
        try:
            got = json.loads(CACHE.read_text(encoding="utf-8"))
            if now - float(got["at"]) < CACHE_S:
                return got["data"], float(got["at"])
        except (OSError, ValueError, KeyError, TypeError):
            pass
    req = urllib.request.Request(URL, headers={"x-api-key": api_key, "User-Agent": "ai_stats"})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = json.loads(r.read().decode("utf-8"))
    data = body.get("data") or []
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps({"at": now, "data": data}), encoding="utf-8")
    except OSError:
        pass
    return data, now


def _score(m: dict, field: str):
    v = (m.get("evaluations") or {}).get(field)
    return float(v) if isinstance(v, (int, float)) else None


def top(models: list[dict], field: str, n: int = 10) -> list[dict]:
    """The n models with the highest `field`, models without it left out."""
    have = [m for m in models if _score(m, field) is not None]
    have.sort(key=lambda m: (-_score(m, field), str(m.get("name") or "")))
    return have[:n]


def _cell(v, pct: bool = False) -> str:
    if v is None:
        return "—"
    return f"{v * 100:.1f}%" if pct and v <= 1 else f"{v:.1f}"


def _maker(m: dict) -> str:
    return str((m.get("model_creator") or {}).get("name") or "")


def report(models: list[dict], at: float, n: int = 10) -> str:
    # the project's ONE date format (CLAUDE.md, "Date format")
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
    from tradingagents.positions_view import fmt_when

    out = [f"Top {n} AI models — read {fmt_when(at)}, {len(models)} models listed", ""]
    out += [f"CODING (Coding Index, higher is better)",
            "| # | Model | Maker | Coding | LiveCodeBench | SciCode |",
            "|---|---|---|---|---|---|"]
    for i, m in enumerate(top(models, "artificial_analysis_coding_index", n), 1):
        out.append(f"| {i} | {m.get('name')} | {_maker(m)} | "
                   f"{_cell(_score(m, 'artificial_analysis_coding_index'))} | "
                   f"{_cell(_score(m, 'livecodebench'), True)} | {_cell(_score(m, 'scicode'), True)} |")
    out += ["", "REASONING (Intelligence Index, higher is better)",
            "| # | Model | Maker | Intelligence | GPQA | Humanity's Last Exam |",
            "|---|---|---|---|---|---|"]
    for i, m in enumerate(top(models, "artificial_analysis_intelligence_index", n), 1):
        out.append(f"| {i} | {m.get('name')} | {_maker(m)} | "
                   f"{_cell(_score(m, 'artificial_analysis_intelligence_index'))} | "
                   f"{_cell(_score(m, 'gpqa'), True)} | {_cell(_score(m, 'hle'), True)} |")
    out += ["", CREDIT]
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--fresh", action="store_true")
    a = ap.parse_args(argv)
    k = key()
    if not k:
        print(NO_KEY)
        return 2
    try:
        models, at = fetch(k, fresh=a.fresh)
    except urllib.error.HTTPError as e:
        why = {401: "the key was refused - check it", 403: "the key was refused - check it",
               429: "the daily limit of 1,000 asks is used up - try again tomorrow"}.get(e.code, "")
        print(f"Artificial Analysis answered HTTP {e.code}{': ' + why if why else ''}")
        return 1
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        print(f"Could not read Artificial Analysis: {type(e).__name__}: {e}")
        return 1
    if not models:
        print("Artificial Analysis answered with no models.")
        return 1
    print(report(models, at, max(1, a.top)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
